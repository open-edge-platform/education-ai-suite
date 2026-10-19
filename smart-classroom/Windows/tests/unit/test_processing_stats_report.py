# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Scripts/processing_stats_report.py: sources, timeline lanes and report tables."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "Scripts" / "processing_stats_report.py"


def _load():
    # By path: a `scripts` namespace package from pywin32 can shadow this directory.
    spec = importlib.util.spec_from_file_location("_processing_stats_report", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rep = _load()

SID = "20261017-235509-d65d"
STAGES = [
    {"session_id": SID, "stage": "transcribe", "status": "done", "duration_sec": 100.0,
     "started_at": "2026-10-17T15:55:00.000+00:00", "ended_at": "2026-10-17T15:56:40.000+00:00"},
    {"session_id": SID, "stage": "summarize", "status": "failed", "duration_sec": 0.0,
     "started_at": "2026-10-17T15:56:41.000+00:00", "ended_at": "2026-10-17T15:56:41.000+00:00"},
]


def _call(capability, stage, submitted, latency_ms, status="ok", **extra):
    return {"session_id": SID, "capability": capability, "stage": stage, "status": status,
            "model": "m", "submitted_at": submitted, "queue_wait_ms": 500.0,
            "latency_ms": latency_ms, **extra}


CALLS = [
    _call("asr", "transcribe", "2026-10-17T15:55:00.000+00:00", 40_000.0),
    # Board OCR has no stage record: its lane is derived from the calls.
    _call("ocr", "board_ocr", "2026-10-17T15:55:10.000+00:00", 1_000.0),
    _call("ocr", "board_ocr", "2026-10-17T15:55:20.000+00:00", 2_000.0),
    _call("text_gen", "summarize", "2026-10-17T15:56:41.000+00:00", None, status="rejected"),
    _call("text_gen", "mindmap", "2026-10-17T15:56:45.000+00:00", 10_000.0,
          draft_tokens=100, accepted_tokens=75, ttft_ms=900.0),
]


def _session_dir(tmp_path):
    logs = tmp_path / SID / "logs"
    logs.mkdir(parents=True)
    (logs / "stage_events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in STAGES) + "\n{partial", encoding="utf-8")
    (logs / "model_calls.jsonl").write_text(
        "\n".join(json.dumps(r) for r in CALLS), encoding="utf-8")
    return tmp_path / SID


def test_lanes_derive_untracked_stages_and_skip_rejected_calls():
    lanes = {(label, kind): blocks for label, kind, blocks in rep.lanes(STAGES, CALLS)}
    (start, end, status), = lanes[("board_ocr", "derived")]
    assert end - start == pytest.approx(10.0 + 2.0)  # first call admitted -> last call ended
    assert status == "ok"
    assert len(lanes[("text_gen calls", "calls")]) == 1  # the rejected call never ran
    assert ("mindmap", "derived") in lanes and ("summarize", "stage") in lanes


def test_session_directory_report(tmp_path):
    text = rep.report([str(_session_dir(tmp_path))])
    assert "```mermaid\n---\ndisplayMode: compact\n---\ngantt" in text
    assert "    section board_ocr *" in text
    # A stage that failed at once still gets a 1 ms bar, marked critical.
    assert "summarize 0.0s :crit, 1792252601000, 1792252601001" in text
    assert re.search(r"^board_ocr \* +\|.*░", text, re.M)  # plain-text lane
    assert "| board_ocr * | from calls |" in text
    assert "75 / 100 (75%)" in text
    assert "| summarize | 0 ⚠ |" not in text and "| summarize | 0 |" in text


def test_api_json_source_requires_raw_records(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps({"raw": {"stages": STAGES, "model_calls": CALLS}}),
                    encoding="utf-8")
    assert "## Session `20261017-235509-d65d`" in rep.report([str(path)])
    path.write_text(json.dumps({"stages": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="raw=true"):
        rep.report([str(path)])


def test_powershell_export_with_bom_is_read(tmp_path):
    path = tmp_path / "stats.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(
        {"raw": {"stages": STAGES, "model_calls": CALLS}}).encode("utf-8"))
    assert "## Session `20261017-235509-d65d`" in rep.report([str(path)])


def test_stage_rows_count_each_attempts_own_calls_including_failures():
    stages = [
        {"session_id": SID, "stage": "summarize", "status": "failed", "duration_sec": 70.0,
         "started_at": "2026-10-17T15:00:00.000+00:00"},
        {"session_id": SID, "stage": "summarize", "status": "done", "duration_sec": 20.0,
         "started_at": "2026-10-17T15:02:00.000+00:00"},
    ]
    calls = [
        # The first attempt's only call ran 60 s and then failed.
        _call("text_gen", "summarize", "2026-10-17T15:00:01.000+00:00", 60_000.0,
              status="failed"),
        _call("text_gen", "summarize", "2026-10-17T15:02:01.000+00:00", 15_000.0),
    ]
    text = rep.session_section(SID, stages, calls)
    assert "| summarize | failed | 0.0 | 70.0 | 70.0 | 1 | 60.0 | 0.5 |" in text
    assert "| summarize | done | 120.0 | 140.0 | 20.0 | 1 | 15.0 | 0.5 |" in text


def test_acceptance_needs_both_counters():
    calls = [_call("text_gen", "summarize", "2026-10-17T15:56:45.000+00:00", 1_000.0,
                   draft_tokens=100)]
    row = next(line for line in rep.calls_table(calls).splitlines() if "text_gen" in line)
    assert "| — |" in row


def test_cli_writes_the_report(tmp_path):
    out = tmp_path / "report.md"
    assert rep.main([str(_session_dir(tmp_path)), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("# Processing-Time Report")
