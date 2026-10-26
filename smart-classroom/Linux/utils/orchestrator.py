import logging
import os
import threading

from pipeline import Pipeline
from dto.transcription_dto import TranscriptionRequest
from dto.audiosource import AudioSource
from utils.storage_manager import StorageManager
from utils.session_manager import generate_session_id
from utils import session_store
from utils.session_paths import SessionPaths
from utils.session_log import session_log_handler, bind_session
from utils.stage_tracker import stage_tracker

logger = logging.getLogger(__name__)


class _OrchestrationError(Exception):
    pass


class _Cancelled(Exception):
    pass


class _ConcurrencyLimit(_OrchestrationError):
    pass


# Number of /sessions/process that may run simultaneously in this process.
# Deliberately small and not exposed to clients; serves as a safety valve so a
# flood of concurrent requests cannot exhaust GPU/CPU/memory.
_MAX_CONCURRENT_SESSIONS = 2


class _RunningTask:
    """Handle for one in-flight session's background work (A1 registry)."""

    def __init__(self, thread, cancel_event):
        self.thread = thread
        self.cancel_event = cancel_event


_RUNNING: dict[str, _RunningTask] = {}
_RUNNING_LOCK = threading.Lock()


def running_session_ids() -> list:
    with _RUNNING_LOCK:
        return list(_RUNNING.keys())


def request_cancel(session_id: str) -> bool:
    """Set cancel flag. Returns True if a running task was found."""
    with _RUNNING_LOCK:
        task = _RUNNING.get(session_id)
        if task is None:
            return False
        task.cancel_event.set()
    return True


def _now_iso() -> str:
    from utils.session_store import _now_iso as _store_now
    return _store_now()


def start_process(request: dict) -> str:
    session_id = generate_session_id()
    stages = request.get("stages", [])
    cancel_event = threading.Event()
    thread = threading.Thread(target=_run, args=(session_id, request, stages), daemon=True)
    with _RUNNING_LOCK:
        if len(_RUNNING) >= _MAX_CONCURRENT_SESSIONS:
            raise _ConcurrencyLimit("too many concurrent sessions")
        _RUNNING[session_id] = _RunningTask(thread, cancel_event)
    try:
        thread.start()
    except RuntimeError:
        with _RUNNING_LOCK:
            _RUNNING.pop(session_id, None)
        raise
    session_store.SessionStore.create(session_id, request, stages)
    return session_id


def _run(session_id: str, request: dict, stages: list) -> None:
    with session_log_handler(session_id):
        try:
            _run_inner(session_id, request, stages)
        finally:
            with _RUNNING_LOCK:
                _RUNNING.pop(session_id, None)


def _run_inner(session_id: str, request: dict, stages: list) -> None:
    session_store.SessionStore.update(session_id, state="running")
    _touch_heartbeat(session_id)
    try:
        _run_audio_chain(session_id, request, stages)
        session_store.SessionStore.mark_completed(session_id)
    except _Cancelled:
        session_store.SessionStore.mark_cancelled(session_id)
    except _OrchestrationError as e:
        session_store.SessionStore.mark_failed(session_id, str(e))
    except Exception as e:
        logger.exception(f"[orchestrator] session {session_id} unexpected failure")
        session_store.SessionStore.mark_failed(session_id, f"unexpected error: {e}")


def _touch_heartbeat(session_id: str) -> None:
    session_store.SessionStore.update(session_id, last_heartbeat=_now_iso())


def _check_cancel(session_id: str) -> None:
    with _RUNNING_LOCK:
        task = _RUNNING.get(session_id)
    if task is not None and task.cancel_event.is_set():
        raise _Cancelled("session cancelled")


def _run_audio_chain(session_id: str, request: dict, stages: list) -> None:
    pipeline = Pipeline(session_id)

    if "transcribe" in stages:
        _check_cancel(session_id)
        session_store.SessionStore.set_stage(session_id, "transcribe", "running")
        audio_path = request.get("audio_path")
        if not audio_path:
            raise _OrchestrationError("stage transcribe requires audio_path")
        tr = TranscriptionRequest(audio_filename=audio_path, source_type=AudioSource.AUDIO_FILE)
        _touch_heartbeat(session_id)
        with stage_tracker(session_id, "transcribe"):
            _drain(pipeline.run_transcription(tr))
        session_store.SessionStore.set_stage(session_id, "transcribe", "done")
        _await_pending_writes()

    if "summarize" in stages:
        _check_cancel(session_id)
        session_store.SessionStore.set_stage(session_id, "summarize", "running")
        _touch_heartbeat(session_id)
        with stage_tracker(session_id, "summarize"):
            _drain(pipeline.run_summarizer())
        session_store.SessionStore.set_stage(session_id, "summarize", "done")
        _await_pending_writes()

    if "mindmap" in stages:
        _check_cancel(session_id)
        session_store.SessionStore.set_stage(session_id, "mindmap", "running")
        _touch_heartbeat(session_id)
        with stage_tracker(session_id, "mindmap"):
            pipeline.run_mindmap()
        session_store.SessionStore.set_stage(session_id, "mindmap", "done")

    if "segmentation" in stages:
        _check_cancel(session_id)
        session_store.SessionStore.set_stage(session_id, "segmentation", "running")
        _touch_heartbeat(session_id)
        with stage_tracker(session_id, "segmentation"):
            pipeline.run_content_segmentation()
        session_store.SessionStore.set_stage(session_id, "segmentation", "done")

    if "report" in stages:
        _check_cancel(session_id)
        session_store.SessionStore.set_stage(session_id, "report", "running")
        _touch_heartbeat(session_id)
        with stage_tracker(session_id, "report"):
            _drain(pipeline.run_report_generator())
        session_store.SessionStore.set_stage(session_id, "report", "done")


def _drain(gen) -> None:
    for _ in gen:
        pass


def _await_pending_writes(timeout: float = 30.0) -> None:
    StorageManager.wait_idle(timeout)
