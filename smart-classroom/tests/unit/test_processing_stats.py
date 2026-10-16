# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

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
    with patch.object(ps.time, "monotonic", lambda: next(times)):
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


def test_timed_model_call_records_success_and_failure(stats):
    with patch.object(ps, "STATS", stats):
        ok = ps.timed_model_call(lambda x: x * 2, "asr", lambda: {"model": "whisper"})
        assert ok(4) == 8

        def boom():
            raise RuntimeError("x")

        with pytest.raises(RuntimeError):
            ps.timed_model_call(boom, "ocr", lambda: {})()
    calls = stats.records()[1]
    assert [(c["capability"], c["status"]) for c in calls] == [("asr", "ok"), ("ocr", "failed")]
    assert calls[1]["error_class"] == "RuntimeError"


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
