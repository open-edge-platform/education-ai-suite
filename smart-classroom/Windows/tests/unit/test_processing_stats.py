# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from model_manager.capability.runner import CapabilityRunner, QueueFullError
from utils import processing_stats as ps


@pytest.fixture
def stats():
    store = ps.ProcessingStats(max_records=50)
    with patch.object(ps, "_append_session_line"):
        yield store


def test_distribution_uses_nearest_rank_and_ignores_unavailable():
    d = ps.distribution([5, 1, None, 3, float("nan"), 2, 4, True])
    assert d["count"] == 5 and d["total"] == 15 and d["mean"] == 3
    assert (d["min"], d["max"], d["p50"], d["p95"]) == (1, 5, 3, 5)
    assert d["small_sample"] is True
    empty = ps.distribution([None])
    assert empty["count"] == 0 and empty["mean"] is None and empty["p95"] is None


def test_nearest_rank_p95_on_twenty_samples():
    d = ps.distribution(range(1, 21))
    assert d["p95"] == 19 and d["p50"] == 10 and d["small_sample"] is False


def test_model_call_separates_queue_wait_latency_and_cancellation(stats):
    times = iter([10.0, 10.5, 10.8, 11.0, 12.0])
    with patch.object(ps.time, "perf_counter", lambda: next(times)):
        call = ps.ModelCall("text_gen", model="m", stream=True, recorder=stats)  # 10.0
        call.started()                                                          # 10.5
        call.first_output()                                                     # 10.8
        call.client_cancelled()                                                 # 11.0
        call.update_runtime({"ttft_ms": 120.0, "tpot_ms": None})
        call.finish("ok")                                                       # 12.0
    (record,) = stats.records()[1]
    assert record["queue_wait_ms"] == 500.0
    assert record["latency_ms"] == 1500.0
    assert record["first_output_ms"] == 300.0
    assert record["client_cancelled_after_ms"] == 500.0
    assert record["status"] == "cancelled"
    assert record["ttft_ms"] == 120.0 and "tpot_ms" not in record


def test_finish_is_idempotent_and_unadmitted_call_has_no_latency(stats):
    call = ps.ModelCall("text_gen", recorder=stats)
    call.finish("rejected")
    call.finish("ok")
    (record,) = stats.records()[1]
    assert record["status"] == "rejected" and record["latency_ms"] is None


def test_submit_timed_records_queue_wait_rejection_and_failure(stats):
    runner = CapabilityRunner(ps.run_admitted, max_concurrency=1, queue_max=2)
    admitted, release = threading.Event(), threading.Event()

    def hold():
        admitted.set()
        release.wait(5)
        return "held"

    def boom():
        raise ValueError("x")

    with patch.object(ps, "STATS", stats), ps.stage_scope("s1", "transcribe"), \
            ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(contextvars.copy_context().run,
                            ps.submit_timed, runner, "asr", {"model": "whisper"}, hold)
        assert admitted.wait(5)
        queued = pool.submit(contextvars.copy_context().run,
                             ps.submit_timed, runner, "asr", {}, lambda x: x * 2, 4)
        while runner._current_queue < 2:
            pass
        with pytest.raises(QueueFullError):
            ps.submit_timed(runner, "ocr", {}, hold)
        threading.Timer(0.2, release.set).start()
        assert first.result(5) == "held" and queued.result(5) == 8
        with pytest.raises(ValueError):
            ps.submit_timed(runner, "ocr", {}, boom)
    calls = {(c["capability"], c["status"]): c for c in stats.records()[1]}
    assert set(calls) == {("asr", "ok"), ("ocr", "rejected"), ("ocr", "failed")}
    rejected = calls[("ocr", "rejected")]
    assert rejected["latency_ms"] is None and rejected["stage"] == "transcribe"
    waited = [c for c in stats.records()[1] if c["capability"] == "asr"]
    assert max(c["queue_wait_ms"] for c in waited) >= 150
    assert all(c["session_id"] == "s1" for c in waited)
    assert calls[("ocr", "failed")]["error_class"] == "ValueError"


def _advance_like_starlette(iterator):
    """Each chunk on a worker thread in a fresh context, as iterate_in_threadpool."""
    out = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        while True:
            try:
                out.append(pool.submit(contextvars.Context().run, next, iterator).result())
            except StopIteration:
                return out


def test_context_iterator_keeps_the_stage_for_every_chunk():
    def body():
        with ps.stage_scope("s1", "transcribe"):
            for _ in range(3):
                yield ps.current_stage()

    assert _advance_like_starlette(body())[1:] == [(None, None)] * 2
    assert _advance_like_starlette(ps.ContextIterator(body())) == [("s1", "transcribe")] * 3


def test_stage_scope_attributes_calls_and_resets(stats):
    with ps.stage_scope("s1", "summary"):
        inside = ps.ModelCall("text_gen", recorder=stats)
    outside = ps.ModelCall("text_gen", recorder=stats)
    assert (inside.record["session_id"], inside.record["stage"]) == ("s1", "summary")
    assert outside.record["stage"] is None


def test_snapshot_groups_shared_model_by_stage_and_counts_failures(stats):
    for stage, status, latency in [("summary", "ok", 100), ("summary", "ok", 300),
                                   ("mindmap", "ok", 50), ("mindmap", "failed", 20)]:
        stats.record_call({"capability": "text_gen", "stage": stage, "model": "Q",
                           "precision": "int4", "device": "GPU", "decoding": "plain",
                           "status": status, "latency_ms": latency, "session_id": "s1"})
    stats.record_stage("s1", "summary", "done", 2.5)
    stats.record_stage("s1", "summary", "interrupted", 1.0)
    snap = stats.snapshot(session_id="s1", include_raw=True)

    by_stage = {g["stage"]: g for g in snap["model_calls_by_stage"]}
    assert by_stage["summary"]["latency_ms"]["count"] == 2
    assert by_stage["summary"]["latency_ms"]["mean"] == 200
    assert by_stage["mindmap"]["failed_count"] == 1
    assert by_stage["mindmap"]["latency_ms"]["count"] == 1
    assert by_stage["mindmap"]["ttft_ms"]["count"] == 0  # unavailable, not zero
    (by_model,) = snap["model_calls_by_model"]
    assert by_model["latency_ms"]["count"] == 3
    (stage,) = snap["stages"]
    assert stage["duration_sec"]["count"] == 1 and stage["cancelled_count"] == 1
    assert len(snap["raw"]["model_calls"]) == 4
    assert stats.snapshot(session_id="other")["model_calls_by_model"] == []


def test_retention_is_bounded():
    store = ps.ProcessingStats(max_records=3)
    for i in range(5):
        store.record_stage("s", "asr", "done", i)
    assert [r["duration_sec"] for r in store.records()[0]] == [2, 3, 4]


# --- integration with utils.stage_tracker ---------------------------------------
def _tracker_env():
    return (patch("utils.stage_tracker.StageEventWriter.write"),
            patch("utils.stage_tracker.SessionStore.set_stage"))


def test_stage_tracker_records_stage_and_attributes_threadpool_calls(stats):
    from utils.stage_tracker import stage_tracker

    def endpoint():  # mindmap/segmentation: sync endpoint run in the threadpool
        with stage_tracker("s1", "mindmap"):
            return ps.ModelCall("text_gen", recorder=stats).record["stage"]

    w, s = _tracker_env()
    with w, s, patch.object(ps, "STATS", stats), patch("utils.stage_tracker.STATS", stats):
        with ThreadPoolExecutor(1) as pool:
            assert pool.submit(endpoint).result() == "mindmap"
    (record,) = stats.records()[0]
    assert record["stage"] == "mindmap" and record["status"] == "done"


def test_stage_tracker_attribution_survives_async_generator_steps(stats):
    from utils.stage_tracker import stage_tracker

    async def event_stream():  # summary/report: async generator over the stream
        with stage_tracker("s2", "summary"):
            for _ in range(3):
                yield ps.ModelCall("text_gen", recorder=stats).record["stage"]
                await asyncio.sleep(0)

    async def consume():
        return [item async for item in event_stream()]

    w, s = _tracker_env()
    with w, s, patch("utils.stage_tracker.STATS", stats):
        assert asyncio.run(consume()) == ["summary"] * 3
    assert ps.current_stage() == (None, None)


def test_concurrent_session_lines_are_all_written(tmp_path):
    """Calls finishing together (OCR, ASR, text_gen) each keep their line."""
    from utils.session_paths import SessionPaths

    with patch.object(SessionPaths, "logs_dir", staticmethod(lambda session_id: tmp_path)):
        def write(worker):
            for i in range(500):
                ps._append_session_line({"session_id": "s", "worker": worker, "i": i})

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(4)))
    lines = (tmp_path / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2000
