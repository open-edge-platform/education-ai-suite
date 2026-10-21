import atexit
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import Lock

from utils.processing_stats import STATS, stage_scope
from utils.session_store import SessionStore
from utils.stage_events import StageEventWriter

logger = logging.getLogger(__name__)

# Every stage between its start and its end record: (session_id, stage) ->
# (started_at, perf_counter at start). The end record is written by whoever
# pops the entry first - the stage itself, or close_open_stages() at shutdown.
_OPEN: dict[tuple, tuple] = {}
# Stages close_open_stages() already ended; their own end, should it still
# arrive (an atexit cleanup finishing VA), must not add a second record.
_CLOSED_AT_SHUTDOWN: set = set()
_OPEN_LOCK = Lock()
# Stages timed and recorded like any other, but never mirrored onto the
# session row because no session declares them (board OCR runs beside VA).
SIDE_STAGES = frozenset({"board_ocr"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _open(session_id, stage) -> tuple:
    started = (_now_iso(), time.perf_counter())
    with _OPEN_LOCK:
        _OPEN[(session_id, stage)] = started
        _CLOSED_AT_SHUTDOWN.discard((session_id, stage))
    return started


def _close(session_id, stage) -> tuple | None:
    """The stage's (started_at, t0); None if it was already closed at shutdown."""
    with _OPEN_LOCK:
        started = _OPEN.pop((session_id, stage), None)
        if started is None and (session_id, stage) in _CLOSED_AT_SHUTDOWN:
            return None
    return started or (None, None)


def _store_stage(session_id, stage, status) -> None:
    """Mirror the stage transition onto the session row."""
    if stage in SIDE_STAGES:
        return  # it would otherwise become the session's current_stage
    try:
        SessionStore.set_stage(session_id, stage, status)
    except Exception:
        logger.warning(
            f"[stage] {session_id} {stage}: failed to record '{status}' in the session store",
            exc_info=True,
        )


class StageHandle:
    """Escape hatch for stages that report failure in-band instead of raising.

    A streaming endpoint that catches its own errors and yields them as a payload
    (so the browser gets a message rather than a truncated response) leaves
    nothing for the context manager to see. Such a stage calls `fail(exc)` to say
    so explicitly; everyone else can ignore the handle.
    """

    def __init__(self):
        self.error = None

    def fail(self, exc) -> None:
        if self.error is None:
            self.error = exc


@contextmanager
def stage_tracker(session_id, stage):
    """Wrap a pipeline stage: record start/end/duration/exception to the log, to
    the per-session stage_events.jsonl and to the session store. One
    instrumentation point, three outlets. Re-raises on failure so the caller's
    error handling still runs.
    """
    _open(session_id, stage)
    logger.info(f"[stage] {session_id} {stage} start")
    _store_stage(session_id, stage, "running")
    handle = StageHandle()
    try:
        with stage_scope(session_id, stage):
            yield handle
    except Exception as e:
        _finish(session_id, stage, "failed", e)
        raise
    except BaseException as e:
        # GeneratorExit and asyncio.CancelledError land here: the HTTP client hung
        # up part-way through a streaming stage, or the server is shutting down.
        _finish(session_id, stage, "interrupted", e)
        raise
    else:
        if handle.error is None:
            _finish(session_id, stage, "done", None)
        else:
            _finish(session_id, stage, "failed", handle.error)


def _finish(session_id, stage, status, exc) -> None:
    started = _close(session_id, stage)
    if started is None:
        return  # already recorded as interrupted by close_open_stages()
    started_at, t0 = started
    duration = round(time.perf_counter() - t0, 3) if t0 is not None else None
    ended_at = _now_iso()  # one timestamp, so the API and stage_events.jsonl agree
    STATS.record_stage(session_id, stage, status, duration, started_at, ended_at)
    if exc is None:
        StageEventWriter.write(session_id, stage, status, started_at, ended_at, duration)
        logger.info(f"[stage] {session_id} {stage} {status} in {duration}s")
    else:
        StageEventWriter.write(
            session_id, stage, status, started_at, ended_at, duration,
            error_class=type(exc).__name__, error_detail=str(exc),
        )
        if status == "failed":
            # exc_info=exc rather than logger.exception(): a stage that reported
            # its failure through StageHandle is not inside an except block.
            logger.error(
                f"[stage] {session_id} {stage} failed after {duration}s", exc_info=exc
            )
        else:
            # A disconnect is routine; record it without the traceback noise.
            logger.info(
                f"[stage] {session_id} {stage} interrupted after {duration}s "
                f"({type(exc).__name__})"
            )
    _store_stage(session_id, stage, status)


def stage_started(session_id, stage) -> None:
    """Open a stage whose start and end land in different requests."""
    _open(session_id, stage)
    logger.info(f"[stage] {session_id} {stage} start")
    _store_stage(session_id, stage, "running")


def stage_finished(session_id, stage, status, error_class=None, error_detail=None) -> None:
    """Close out a stage opened with stage_started().

    A stage that never started (a launch that failed outright) is still
    recorded, without a start or duration.
    """
    started = _close(session_id, stage)
    if started is None:
        return  # already recorded as interrupted by close_open_stages()
    started_at, t0 = started
    duration = round(time.perf_counter() - t0, 3) if t0 is not None else None
    ended_at = _now_iso()
    STATS.record_stage(session_id, stage, status, duration, started_at, ended_at)
    StageEventWriter.write(
        session_id, stage, status, started_at, ended_at, duration,
        error_class=error_class, error_detail=error_detail,
    )
    logger.info(
        f"[stage] {session_id} {stage} {status}"
        + (f" in {duration}s" if duration is not None else "")
    )
    _store_stage(session_id, stage, status)


SHUTDOWN_REASON = "application shut down while the stage was running"


def close_open_stages(reason: str = SHUTDOWN_REASON) -> int:
    """Record every stage still running as interrupted; returns how many.

    Called when the server shuts down. A stage running on a daemon thread -
    video analytics above all, which lasts as long as its videos - would
    otherwise be frozen mid-stage at interpreter exit and leave no record at
    all, so the processing-time report could not show that it ran. Each stage
    keeps its real start and the time it had run; if it still ends on its own
    afterwards, that end is not recorded a second time.
    """
    with _OPEN_LOCK:
        open_stages = list(_OPEN.items())
        _OPEN.clear()
        _CLOSED_AT_SHUTDOWN.update(key for key, _ in open_stages)
    for (session_id, stage), (started_at, t0) in open_stages:
        duration = round(time.perf_counter() - t0, 3)
        ended_at = _now_iso()
        try:
            STATS.record_stage(session_id, stage, "interrupted", duration, started_at, ended_at)
            StageEventWriter.write(
                session_id, stage, "interrupted", started_at, ended_at, duration,
                error_class="Shutdown", error_detail=reason,
            )
            logger.info(f"[stage] {session_id} {stage} interrupted after {duration}s (shutdown)")
            _store_stage(session_id, stage, "interrupted")
        except Exception:  # noqa: BLE001 - shutdown must go on
            logger.warning(f"[stage] {session_id} {stage}: shutdown record failed", exc_info=True)
    return len(open_stages)


# A fallback for exits that skip the server's lifespan shutdown. A hard kill
# (taskkill /F) runs neither; the report then reads the VA runner logs.
atexit.register(close_open_stages)
