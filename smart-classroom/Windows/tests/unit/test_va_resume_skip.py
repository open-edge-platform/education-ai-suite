# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""A restarted file pipeline skips a segment it cannot get past.

Resume picks a crashed file pipeline up where it stopped. When the crash comes
from the content -- a corrupt stretch the decoder fails on every time -- each
resume went straight back into it, until the retries ran out and the rest of
the video was lost. A restart that makes no progress now skips ahead instead.

The service is built with object.__new__, as in test_va_pipeline_stop.py, and
reads real metadata files from a temporary directory.
"""

import json
import logging

from components.va.va_pipeline_service import VideoAnalyticsPipelineService

S = 1_000_000_000  # ns per second


def make_service(tmp_path, files=("posture.txt", "classify.txt")):
    svc = object.__new__(VideoAnalyticsPipelineService)
    svc.logger = logging.getLogger("test.va.skip")
    svc.pipeline_errors = {}
    svc.pipeline_resume_state = {}
    svc.pipeline_skipped_segments = {}
    svc.resume_progress_min_sec = 1.0
    svc.resume_skip_first_sec = 1.0
    svc.resume_skip_max_sec = 30.0
    svc.pipeline_output_files = {"back": [tmp_path / f for f in files]}
    return svc


def write(path, *seconds):
    """Append one gvametapublish line per timestamp."""
    with open(path, "a", encoding="utf-8") as fh:
        for s in seconds:
            fh.write(json.dumps({"objects": [], "timestamp": round(s * S)}) + "\n")


def stamps(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l)["timestamp"] / S for l in fh if l.strip()]


def crash_at(svc, tmp_path, posture_to, classify_to, posture_from=None, classify_from=None):
    """Simulate a run writing frames up to the given points, then resume."""
    posture, classify = svc.pipeline_output_files["back"]
    start_p = posture_from if posture_from is not None else (stamps(posture)[-1] + 0.1 if posture.exists() and stamps(posture) else 0.0)
    start_c = classify_from if classify_from is not None else (stamps(classify)[-1] + 1 if classify.exists() and stamps(classify) else 0.0)
    t = start_p
    while t <= posture_to + 1e-9:
        write(posture, round(t, 1)); t += 0.1
    t = start_c
    while t <= classify_to + 1e-9:
        write(classify, round(t)); t += 1
    return svc._prepare_resume("back")


def test_the_first_restart_resumes_where_the_slowest_branch_stopped(tmp_path):
    svc = make_service(tmp_path)
    position = crash_at(svc, tmp_path, posture_to=15.9, classify_to=13)

    assert position == 13 * S
    assert not svc.pipeline_skipped_segments
    assert not svc.pipeline_errors


def test_a_restart_that_fails_at_the_same_point_skips_past_it(tmp_path):
    svc = make_service(tmp_path)
    posture, classify = svc.pipeline_output_files["back"]
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13)
    # The relaunch from 13 s dies at the same frame.
    position = crash_at(svc, tmp_path, posture_to=15.9, classify_to=13,
                        posture_from=13.0, classify_from=13)

    assert position == round(16.9 * S), "one GOP past the furthest frame reached"
    assert svc.pipeline_skipped_segments["back"] == [(round(15.9 * S), round(16.9 * S))]
    assert "Skipped 15.9s-16.9s" in svc.pipeline_errors["back"][0]
    # Frames already written before the skip point are kept, once each.
    assert stamps(posture) == sorted(set(stamps(posture)))
    assert stamps(posture)[-1] == 15.9
    assert stamps(classify)[-1] == 13


def test_each_further_stuck_restart_doubles_the_jump(tmp_path):
    svc = make_service(tmp_path)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13, posture_from=13.0, classify_from=13)
    # Relaunched at 16.9 s, it dies at once, again and again.
    jumps = []
    for _ in range(3):
        position = svc._prepare_resume("back")
        jumps.append(round(position / S - 15.9, 1))

    assert jumps == [2.0, 4.0, 8.0]
    # One stuck point, one skipped stretch -- grown, not repeated.
    assert svc.pipeline_skipped_segments["back"] == [(round(15.9 * S), round(23.9 * S))]


def test_the_jump_is_capped(tmp_path):
    svc = make_service(tmp_path)
    svc.resume_skip_max_sec = 5.0
    crash_at(svc, tmp_path, posture_to=10, classify_to=10)
    positions = [svc._prepare_resume("back") / S for _ in range(5)]

    assert positions == [11.0, 12.0, 14.0, 15.0, 15.0]


def test_progress_after_a_skip_returns_to_normal_resume(tmp_path):
    svc = make_service(tmp_path)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13, posture_from=13.0, classify_from=13)
    # Resumed at 16.9 s, this run gets well past the bad stretch.
    position = crash_at(svc, tmp_path, posture_to=40.0, classify_to=38,
                        posture_from=16.9, classify_from=17)

    assert position == 38 * S, "back to resuming at the slowest branch"
    assert svc.pipeline_resume_state["back"]["stuck"] == 0
    assert len(svc.pipeline_skipped_segments["back"]) == 1


def test_a_new_stuck_point_after_progress_is_a_separate_segment(tmp_path):
    svc = make_service(tmp_path)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13, posture_from=13.0, classify_from=13)
    crash_at(svc, tmp_path, posture_to=40.0, classify_to=38, posture_from=16.9, classify_from=17)
    # A second corrupt stretch further on: stuck at 40 s, twice.
    svc._prepare_resume("back")
    svc._prepare_resume("back")

    assert svc.pipeline_skipped_segments["back"] == [
        (round(15.9 * S), round(16.9 * S)),
        (40 * S, 42 * S),
    ]


def test_a_branch_left_behind_the_skip_does_not_pull_the_resume_back_into_it(tmp_path):
    """The 1 fps branch may write nothing between a skip and the next crash."""
    svc = make_service(tmp_path)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13)
    crash_at(svc, tmp_path, posture_to=15.9, classify_to=13, posture_from=13.0, classify_from=13)
    # Relaunched at 16.9 s, the posture branch gets 3 s further; classify writes nothing.
    position = crash_at(svc, tmp_path, posture_to=19.9, classify_to=-1,
                        posture_from=16.9, classify_from=99)

    assert position >= round(16.9 * S), "must not resume inside the skipped 15.9-16.9 s"
    assert all(not (15.9 < t < 16.9) for t in stamps(svc.pipeline_output_files["back"][0]))


def test_a_pipeline_that_has_written_nothing_starts_from_the_top_then_skips(tmp_path):
    svc = make_service(tmp_path)

    assert svc._prepare_resume("back") is None, "first restart: from the top"
    assert svc._prepare_resume("back") == 1 * S, "stuck at the top: skip the first second"
