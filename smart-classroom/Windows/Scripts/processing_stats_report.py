#!/usr/bin/env python
# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Turn processing-time statistics into a Markdown report with a timing diagram.

    python Scripts/processing_stats_report.py storage/smart-classroom/<session>
    python Scripts/processing_stats_report.py stats.json -o report.md
    python Scripts/processing_stats_report.py <session dir> <session dir> ...

A source is a session directory (its ``logs/stage_events.jsonl`` and
``logs/model_calls.jsonl``, which survive restarts) or the JSON saved from
``GET /processing-stats?raw=true``. Each session gets a timeline: one lane per
workflow stage plus one per model capability, drawn as a Mermaid Gantt chart
and as plain text. Distributions reuse ``utils.processing_stats``, so they match
the API. See docs/vlm-llm-serving/processing-time-statistics.md.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from utils.processing_stats import call_groups, stage_groups  # noqa: E402  (needs _ROOT)

_OK_STAGE, _OK_CALL = "done", "ok"
_WIDTH = 64  # columns of the plain-text timeline


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # a crash mid-append can leave a partial last line
    return rows


def load(source: Path) -> tuple:
    """Return ``(stages, calls)`` records from a session directory or API JSON."""
    if not source.exists():
        raise SystemExit(f"{source}: not found (run from the app root, smart-classroom/Windows)")
    if source.is_dir():
        logs = source / "logs" if (source / "logs").is_dir() else source
        return _jsonl(logs / "stage_events.jsonl"), _jsonl(logs / "model_calls.jsonl")
    # utf-8-sig: Windows PowerShell 5.1 "Set-Content -Encoding utf8" writes a BOM.
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    raw = data.get("raw")
    if raw is None:
        raise SystemExit(f"{source}: no raw records; save GET /processing-stats?raw=true")
    return raw.get("stages", []), raw.get("model_calls", [])


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------
def _ts(text):
    try:
        return datetime.fromisoformat(text).timestamp() if text else None
    except ValueError:
        return None


def stage_interval(r):
    start = _ts(r.get("started_at"))
    if start is None:
        return None
    duration = r.get("duration_sec")
    end = start + duration if isinstance(duration, (int, float)) else _ts(r.get("ended_at"))
    return (start, end) if end is not None else None


def call_interval(r):
    """Admission to end of the call; rejected calls never ran."""
    submitted, latency = _ts(r.get("submitted_at")), r.get("latency_ms")
    if submitted is None or not isinstance(latency, (int, float)):
        return None
    start = submitted + (r.get("queue_wait_ms") or 0) / 1000.0
    return start, start + latency / 1000.0


def lanes(stages: list, calls: list) -> list:
    """``[(label, kind, [(start, end, status)])]`` in order of first activity.

    kind is ``stage``, ``derived`` (a stage seen only through its model calls,
    such as board OCR or an interrupted stage) or ``calls``.
    """
    out = {}
    for r in stages:
        span = stage_interval(r)
        if span:
            out.setdefault((r.get("stage"), "stage"), []).append((*span, r.get("status")))
    tracked = {stage for stage, _ in out}
    for r in calls:
        span = call_interval(r)
        if not span:
            continue
        out.setdefault((f"{r.get('capability')} calls", "calls"), []).append(
            (*span, r.get("status")))
        stage = r.get("stage")
        if stage not in tracked:
            out.setdefault((stage or "unattributed", "derived"), []).append(
                (*span, r.get("status")))
    result = []
    for (label, kind), blocks in out.items():
        if kind == "derived":
            # One span from the first to the last call of that stage.
            failed = any(s != _OK_CALL for _, _, s in blocks)
            blocks = [(min(b[0] for b in blocks), max(b[1] for b in blocks),
                       "failed" if failed else _OK_CALL)]
        result.append((label, kind, sorted(blocks)))
    order = {"stage": 0, "derived": 0, "calls": 1}
    return sorted(result, key=lambda lane: (order[lane[1]], lane[2][0][0]))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _ok(kind, status):
    return status == (_OK_CALL if kind in ("calls", "derived") else _OK_STAGE)


def _num(value, digits=1):
    return "—" if value is None else f"{value:,.{digits}f}"


def mermaid(session: str, rows: list) -> str:
    lines = ["```mermaid", "---", "displayMode: compact", "---", "gantt",
             f"    title Session {session}", "    dateFormat x", "    axisFormat %H:%M:%S"]
    for label, kind, blocks in rows:
        lines.append(f"    section {label}{' *' if kind == 'derived' else ''}")
        for start, end, status in blocks:
            tag = "" if _ok(kind, status) else "crit, "
            if kind == "derived" and _ok(kind, status):
                tag = "active, "
            name = f"{label.split()[0]} {end - start:.1f}s"
            # At least 1 ms, so a stage that failed at once still gets a bar.
            first = int(start * 1000)
            lines.append(f"    {name} :{tag}{first}, {max(first + 1, int(end * 1000))}")
    lines.append("```")
    return "\n".join(lines)


def ascii_chart(rows: list, t0: float, t1: float, width: int = _WIDTH) -> str:
    span = max(t1 - t0, 1e-3)

    def col(t):
        return min(width - 1, max(0, int((t - t0) / span * width)))

    label_w = max(len(label) + 2 for label, _, _ in rows)
    lines = []
    for label, kind, blocks in rows:
        cells = [" "] * width
        for start, end, status in blocks:
            mark = "█" if _ok(kind, status) else "X"
            if kind == "derived" and mark == "█":
                mark = "░"
            for i in range(col(start), max(col(start), col(end)) + 1):
                cells[i] = mark
        name = f"{label} *" if kind == "derived" else label
        lines.append(f"{name:<{label_w}}|{''.join(cells)}|")
    axis = [" "] * (width + 1)
    marks = ["-"] * width
    for k in range(5):
        c = min(width - 1, round(k * (width - 1) / 4))
        marks[c] = "+"
        text = f"{k * span / 4:.0f}s"
        at = max(0, min(c - len(text) // 2, width + 1 - len(text)))
        axis[at:at + len(text)] = text
    lines.append(" " * label_w + "+" + "".join(marks) + "+")
    lines.append(" " * (label_w + 1) + "".join(axis).rstrip())
    return "```text\n" + "\n".join(lines) + "\n```"


def _calls_per_attempt(calls, stage, blocks):
    """Model calls of each attempt (block) of ``stage``.

    Attempts of one stage run one after another (a retry starts after the
    previous attempt ended), so a call belongs to the last attempt that started
    before it was submitted; a call without a usable time goes to the first.
    """
    per = [[] for _ in blocks]
    for r in calls:
        if r.get("stage") != stage:
            continue
        submitted = _ts(r.get("submitted_at"))
        index = 0
        if submitted is not None:
            # Both timestamps have millisecond resolution.
            started = [i for i, b in enumerate(blocks) if b[0] <= submitted + 0.001]
            index = started[-1] if started else 0
        per[index].append(r)
    return per


def _totals(rows):
    """Call count, model time and queue wait (s); model time includes failed and
    cancelled calls, whose inference still occupied the stage."""
    model = sum(r.get("latency_ms") or 0 for r in rows) / 1000.0
    queued = sum(r.get("queue_wait_ms") or 0 for r in rows) / 1000.0
    return len(rows), model, queued


def session_section(session: str, stages: list, calls: list) -> str:
    rows = lanes(stages, calls)
    if not rows:
        return f"## Session `{session}`\n\nNo timed records.\n"
    t0 = min(b[0] for _, _, blocks in rows for b in blocks)
    t1 = max(b[1] for _, _, blocks in rows for b in blocks)
    out = [f"## Session `{session}`", "",
           f"Workflow window: **{t1 - t0:,.1f} s**, from "
           f"{datetime.fromtimestamp(t0).astimezone().isoformat(timespec='seconds')} "
           "to the end of the last stage or call."]
    transcribe = [stage_interval(r) for r in stages
                  if r.get("stage") == "transcribe" and stage_interval(r)]
    if transcribe:
        tail = t1 - max(end for _, end in transcribe)
        out.append(f"After transcription ended, the remaining outputs took **{tail:,.1f} s**.")
    out += ["", "### Timeline", "",
            "Lanes run in parallel; overlapping stages are expected, so stage durations "
            "do not add up to the workflow window. `*` marks a stage seen only through "
            "its model calls (first call to last call).", "",
            mermaid(session, rows), "",
            "Plain-text view (`█` completed, `░` derived from model calls, `X` failed, "
            "interrupted or cancelled):", "",
            ascii_chart(rows, t0, t1), "",
            "### Stages", "",
            "| Stage | Status | Start (s) | End (s) | Duration (s) | Model calls | "
            "Model time (s) | Queue wait (s) |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for label, kind, blocks in rows:
        if kind == "calls":
            continue
        stage = None if label == "unattributed" else label
        for (start, end, status), attempt in zip(blocks,
                                                 _calls_per_attempt(calls, stage, blocks)):
            n, model, queued = _totals(attempt)
            name, shown = (f"{label} *", "from calls") if kind == "derived" else (label, status)
            out.append(f"| {name} | {shown} | {start - t0:,.1f} | {end - t0:,.1f} | "
                       f"{end - start:,.1f} | {n} | {model:,.1f} | {queued:,.1f} |")
    out.append("")
    return "\n".join(out)


def calls_table(calls: list) -> str:
    groups = call_groups(calls, ("capability", "stage", "model", "precision", "device",
                                 "decoding"))
    if not groups:
        return "No model calls recorded.\n"
    out = ["| Capability | Stage | Model | Precision | Device | Decoding | OK | "
           "Latency p50 / p95 (ms) | Queue wait p95 (ms) | TTFT p50 (ms) | "
           "Decode p50 (tok/s) | Tokens in / out | Accepted / drafted | Failed / cancelled |",
           "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | "
           "---: | ---: |"]
    for g in groups:
        lat = g["latency_ms"]
        # Paired samples only: a call missing either counter is left out.
        acc = g["acceptance"]
        acceptance = "—"
        if acc["calls"]:
            acceptance = (f"{_num(acc['accepted'], 0)} / {_num(acc['drafted'], 0)} "
                          f"({acc['rate']:.0%})")
            if acc["calls"] < lat["count"]:
                acceptance += f", {acc['calls']} of {lat['count']} calls"
        out.append(
            f"| {g['capability']} | {g['stage'] or '—'} | {g['model'] or '—'} | "
            f"{g['precision'] or '—'} | {g['device'] or '—'} | {g['decoding'] or '—'} | "
            f"{lat['count']}{' ⚠' if lat.get('small_sample') else ''} | "
            f"{_num(lat['p50'], 0)} / {_num(lat['p95'], 0)} | "
            f"{_num(g['queue_wait_ms']['p95'], 0)} | {_num(g['ttft_ms']['p50'], 0)} | "
            f"{_num(g['decode_tps']['p50'])} | {_num(g['input_tokens']['total'], 0)} / "
            f"{_num(g['output_tokens']['total'], 0)} | {acceptance} | "
            f"{g['failed_count']} / {g['cancelled_count']} |")
    return "\n".join(out) + "\n"


def stages_table(stages: list) -> str:
    out = ["| Stage | Completed | Mean (s) | p50 (s) | p95 (s) | Min / max (s) | "
           "Failed | Interrupted |",
           "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for g in stage_groups(stages):
        d = g["duration_sec"]
        out.append(f"| {g['stage']} | {d['count']}{' ⚠' if d.get('small_sample') else ''} | "
                   f"{_num(d['mean'])} | {_num(d['p50'])} | {_num(d['p95'])} | "
                   f"{_num(d['min'])} / {_num(d['max'])} | {g['failed_count']} | "
                   f"{g['cancelled_count']} |")
    return "\n".join(out) + "\n"


def report(sources: list, session: str = None) -> str:
    stages, calls = [], []
    for source in sources:
        s, c = load(Path(source))
        stages += s
        calls += c
    if session:
        stages = [r for r in stages if r.get("session_id") == session]
        calls = [r for r in calls if r.get("session_id") == session]
    sessions = sorted({r.get("session_id") for r in stages + calls if r.get("session_id")})
    out = ["# Processing-Time Report", "",
           f"Sources: {', '.join(f'`{s}`' for s in sources)}. "
           f"{len(sessions)} session(s), {len(stages)} stage record(s), "
           f"{len(calls)} model call(s). Stage times are seconds, model-call times "
           "milliseconds; `—` is unavailable, never zero.", ""]
    for sid in sessions:
        out.append(session_section(
            sid, [r for r in stages if r.get("session_id") == sid],
            [r for r in calls if r.get("session_id") == sid]))
    unattributed = [r for r in calls if not r.get("session_id")]
    out += ["## Stage Durations", "",
            "Completed attempts only; failed and interrupted attempts are counted "
            "separately. Percentiles are nearest-rank; ⚠ marks fewer than 20 samples "
            "(an observation, not a distribution).", "",
            stages_table(stages),
            "## Model Calls", "",
            "Latency runs from admission to the end of the call; queue wait is "
            "separate. TTFT and decode throughput are runtime-reported. "
            f"{len(unattributed)} call(s) had no session (for example chat API calls).",
            "", calls_table(calls)]
    return "\n".join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="+",
                        help="session directory or JSON from GET /processing-stats?raw=true")
    parser.add_argument("-o", "--output", help="write the report here (default: stdout)")
    parser.add_argument("--session", help="only this session id")
    args = parser.parse_args(argv)
    text = report(args.sources, args.session)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {args.output}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
