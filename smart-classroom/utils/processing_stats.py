# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Processing-time statistics for workflow stages and individual model calls.

Two nested measurements, kept apart on purpose:

* **Stage records** come from ``utils.stage_tracker`` -- one per stage attempt,
  wall time from execution start through the stage's saved output.
* **Model-call records** come from the model owners (text_gen, ASR, OCR) -- one
  per invocation, timed after admission so queue wait is reported separately.

``stage_scope`` publishes the active stage through a ``ContextVar`` so a model
call made while a stage is open is attributed to it; a shared Qwen model then
shows up per Summary/Mindmap/segmentation/report instead of as one total.

Records carry timing metadata only -- never prompts, transcripts, images, tool
arguments or private paths -- and are retained in bounded in-memory buffers,
plus one JSON line per call in the owning session's logs.
"""

from __future__ import annotations

import contextvars
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterable, Iterator, Optional

logger = logging.getLogger(__name__)

# Bounded retention: enough for many sessions of repeated calls, small enough
# that a long-running server never grows without limit.
MAX_RECORDS = 4000

# Below this many samples a p95 is an observation, not a distribution.
SMALL_SAMPLE_WARNING = 20

_STAGE: contextvars.ContextVar = contextvars.ContextVar("sc_processing_stage", default=None)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@contextmanager
def stage_scope(session_id, stage):
    """Attribute model calls made inside the block to ``(session_id, stage)``."""
    token = _STAGE.set((session_id, stage))
    try:
        yield
    finally:
        try:
            _STAGE.reset(token)
        except ValueError:
            # Closed from a different context (e.g. a generator finalized by
            # another task); that context never saw the value, so nothing leaks.
            pass


def current_stage() -> tuple:
    """Return ``(session_id, stage)`` for the open stage, or ``(None, None)``."""
    return _STAGE.get() or (None, None)


class ContextIterator:
    """Advance a sync iterator inside one persistent context.

    Starlette advances a sync streaming body through separate threadpool calls,
    each in a fresh context copy, so a ``stage_scope`` opened inside the
    generator would only cover its first chunk.
    """

    def __init__(self, iterator: Iterator) -> None:
        self._iterator = iterator
        self._context = contextvars.copy_context()

    def __iter__(self) -> "ContextIterator":
        return self

    def __next__(self):
        return self._context.run(next, self._iterator)

    def close(self) -> None:
        close = getattr(self._iterator, "close", None)
        if close is not None:
            self._context.run(close)


class ModelCall:
    """One model invocation, from submission through the end of native work.

    The owner calls :meth:`started` once admission is granted, may call
    :meth:`first_output` and :meth:`update_runtime`, and ends with exactly one
    :meth:`finish`. :meth:`client_cancelled` stamps a client disconnect without
    ending the call, so continuing native inference is still timed.
    """

    def __init__(self, capability: str, *, model=None, precision=None, device=None,
                 decoding=None, artifact=None, stream: bool = False,
                 recorder: Optional["ProcessingStats"] = None) -> None:
        session_id, stage = current_stage()
        self._recorder = recorder or STATS
        self._lock = threading.Lock()
        self._submitted = time.monotonic()
        self._started: Optional[float] = None
        self._first: Optional[float] = None
        self._cancelled: Optional[float] = None
        self._finished = False
        self.runtime: dict = {}
        self.record: dict = {
            "id": uuid.uuid4().hex,
            "capability": capability,
            "stage": stage,
            "session_id": session_id,
            "model": model,
            "precision": precision,
            "device": device,
            "decoding": decoding,
            "artifact": artifact,
            "stream": bool(stream),
            "submitted_at": _now_iso(),
        }

    def started(self) -> None:
        with self._lock:
            if self._started is None:
                self._started = time.monotonic()

    def first_output(self) -> None:
        with self._lock:
            if self._first is None and self._started is not None:
                self._first = time.monotonic()

    def client_cancelled(self) -> None:
        with self._lock:
            if self._cancelled is None:
                self._cancelled = time.monotonic()

    def update_runtime(self, values: dict) -> None:
        """Merge runtime-reported metrics; ``None`` values are dropped, not zeroed."""
        with self._lock:
            self.runtime.update({k: v for k, v in values.items() if v is not None})

    def finish(self, status: str = "ok", error: Optional[BaseException] = None) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            end = time.monotonic()
            record = dict(self.record)
            if self._cancelled is not None and status == "ok":
                status = "cancelled"
            record["status"] = status
            record["error_class"] = type(error).__name__ if error is not None else None
            if self._started is None:
                # Never admitted (queue full, or failed before the owner ran).
                record["queue_wait_ms"] = _ms(end - self._submitted)
                record["latency_ms"] = None
            else:
                record["queue_wait_ms"] = _ms(self._started - self._submitted)
                record["latency_ms"] = _ms(end - self._started)
            record["first_output_ms"] = (
                _ms(self._first - self._started) if self._first is not None else None
            )
            record["client_cancelled_after_ms"] = (
                _ms(self._cancelled - self._started)
                if self._cancelled is not None and self._started is not None else None
            )
            record.update(self.runtime)
        self._recorder.record_call(record)


def _ms(seconds: float) -> float:
    return round(seconds * 1000.0, 3)


def run_admitted(call: ModelCall, fn: Callable, *args, **kwargs):
    """``CapabilityRunner`` callable for :func:`submit_timed`; runs after admission."""
    call.started()
    try:
        result = fn(*args, **kwargs)
    except BaseException as exc:
        call.finish("failed" if isinstance(exc, Exception) else "cancelled", exc)
        raise
    call.finish("ok")
    return result


def submit_timed(runner, capability: str, info: dict, fn: Callable, *args, **kwargs):
    """Submit a non-streaming ``fn`` through a runner built on :func:`run_admitted`.

    As for text generation, the record exists before submission, so queue wait
    is measured and a rejected submission is still recorded; it is attributed
    to the stage open in the caller's context.
    """
    call = ModelCall(capability, **info)
    try:
        return runner.submit(call, fn, *args, **kwargs)
    except BaseException as exc:
        # No-op when run_admitted already finished the record.
        call.finish("rejected" if type(exc).__name__ == "QueueFullError" else "failed", exc)
        raise


class ProcessingStats:
    """Thread-safe bounded store of stage and model-call records."""

    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        self._lock = threading.Lock()
        self._stages: deque = deque(maxlen=max_records)
        self._calls: deque = deque(maxlen=max_records)

    def record_stage(self, session_id, stage, status, duration_sec,
                     started_at=None, ended_at=None) -> None:
        record = {
            "session_id": session_id,
            "stage": stage,
            "status": status,
            "duration_sec": duration_sec,
            "started_at": started_at,
            "ended_at": ended_at,
        }
        with self._lock:
            self._stages.append(record)

    def record_call(self, record: dict) -> None:
        with self._lock:
            self._calls.append(record)
        _append_session_line(record)

    def clear(self) -> None:
        with self._lock:
            self._stages.clear()
            self._calls.clear()

    def records(self, session_id=None) -> tuple:
        with self._lock:
            stages = list(self._stages)
            calls = list(self._calls)
        if session_id is not None:
            stages = [r for r in stages if r.get("session_id") == session_id]
            calls = [r for r in calls if r.get("session_id") == session_id]
        return stages, calls

    def snapshot(self, session_id=None, include_raw: bool = False) -> dict:
        stages, calls = self.records(session_id)
        out = {
            "generated_at": _now_iso(),
            "session_id": session_id,
            "percentile_method": "nearest-rank on sorted successful samples",
            "small_sample_warning_below": SMALL_SAMPLE_WARNING,
            "units": {"stage": "seconds", "model_call": "milliseconds", "throughput": "tokens/s"},
            "retention": {"max_records": self._calls.maxlen},
            "stages": stage_groups(stages),
            "model_calls_by_stage": call_groups(
                calls, ("capability", "stage", "model", "precision", "device", "decoding")
            ),
            "model_calls_by_model": call_groups(
                calls, ("capability", "model", "precision", "device", "decoding")
            ),
        }
        if include_raw:
            out["raw"] = {"stages": stages, "model_calls": calls}
        return out


# Statuses that count as a completed sample; everything else is reported
# separately so a failure is never folded into the latency distribution.
_STAGE_OK = {"done"}
_STAGE_CANCELLED = {"interrupted"}
_CALL_OK = {"ok"}
_CALL_CANCELLED = {"cancelled"}

_CALL_METRICS = ("latency_ms", "queue_wait_ms", "first_output_ms", "ttft_ms",
                 "tpot_ms", "decode_tps", "input_tokens", "output_tokens")


def distribution(values: Iterable) -> dict:
    """Count/total/mean/min/max/p50/p95 over finite values; empty -> unavailable."""
    samples = sorted(
        float(v) for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool)
        and math.isfinite(v) and v >= 0
    )
    n = len(samples)
    if n == 0:
        return {"count": 0, "total": None, "mean": None, "min": None, "max": None,
                "p50": None, "p95": None}
    total = sum(samples)
    return {
        "count": n,
        "total": round(total, 3),
        "mean": round(total / n, 3),
        "min": round(samples[0], 3),
        "max": round(samples[-1], 3),
        "p50": round(_nearest_rank(samples, 50), 3),
        "p95": round(_nearest_rank(samples, 95), 3),
        "small_sample": n < SMALL_SAMPLE_WARNING,
    }


def _nearest_rank(sorted_samples: list, pct: float) -> float:
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_samples)))
    return sorted_samples[rank - 1]


def _outcomes(records: list, ok: set, cancelled: set, duration_key: str) -> dict:
    failed = [r for r in records if r.get("status") not in ok | cancelled]
    stopped = [r for r in records if r.get("status") in cancelled]
    return {
        "failed_count": len(failed),
        "failed_elapsed": distribution(r.get(duration_key) for r in failed)["total"],
        "cancelled_count": len(stopped),
        "cancelled_elapsed": distribution(r.get(duration_key) for r in stopped)["total"],
    }


def stage_groups(records: list) -> list:
    groups: dict = {}
    for r in records:
        groups.setdefault(r.get("stage"), []).append(r)
    out = []
    for stage, rows in sorted(groups.items(), key=lambda kv: str(kv[0])):
        ok = [r for r in rows if r.get("status") in _STAGE_OK]
        entry = {"stage": stage,
                 "duration_sec": distribution(r.get("duration_sec") for r in ok)}
        entry.update(_outcomes(rows, _STAGE_OK, _STAGE_CANCELLED, "duration_sec"))
        out.append(entry)
    return out


def call_groups(records: list, keys: tuple) -> list:
    groups: dict = {}
    for r in records:
        groups.setdefault(tuple(r.get(k) for k in keys), []).append(r)
    out = []
    for group_key, rows in sorted(groups.items(), key=lambda kv: tuple(map(str, kv[0]))):
        ok = [r for r in rows if r.get("status") in _CALL_OK]
        entry = dict(zip(keys, group_key))
        for metric in _CALL_METRICS:
            entry[metric] = distribution(r.get(metric) for r in ok)
        entry.update(_outcomes(rows, _CALL_OK, _CALL_CANCELLED, "latency_ms"))
        out.append(entry)
    return out


def _append_session_line(record: dict) -> None:
    """Mirror a call into ``<session>/logs/model_calls.jsonl``; never raises."""
    session_id = record.get("session_id")
    if not session_id:
        return
    try:
        from utils.session_paths import SessionPaths

        path = SessionPaths.logs_dir(session_id) / "model_calls.jsonl"
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 - observability must not break the flow
        logger.debug("model_calls.jsonl write skipped for %s: %s", session_id, exc)


STATS = ProcessingStats()
