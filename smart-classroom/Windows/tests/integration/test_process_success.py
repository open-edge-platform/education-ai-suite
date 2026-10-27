import json
import re

from tests.integration.conftest import wait_for_state

_SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def _create(client, stages, **extra):
    body = {"stages": stages, **extra}
    resp = client.post("/api/v1/sessions/process", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json(), client


def _await_status(client, session_id):
    state = wait_for_state(client, session_id, timeout=5.0)
    resp = client.get(f"/api/v1/sessions/{session_id}/status")
    return state, resp.json()


# va + report without segmentation must still complete, because the VA thread
# is joined before the session is marked completed (orchestrator finally).
def test_va_report_without_segmentation_completes(client):
    data, client = _create(client, ["va", "report"],
                           video_sources={"front": "rtsp://127.0.0.1:8554/live"})
    session_id = data["session_id"]
    state, status = _await_status(client, session_id)
    assert state == "completed"
    assert status["stages"]["va"] == "done"
    assert status["stages"]["report"] == "done"


# An orchestrated va stage writes class_statistics.json, as the UI path does;
# the report generator reads its VA metrics from that file.
def test_va_writes_class_statistics(client):
    data, client = _create(client, ["va"],
                           video_sources={"front": "rtsp://127.0.0.1:8554/live"})
    session_id = data["session_id"]
    state, _ = _await_status(client, session_id)
    assert state == "completed"

    artifacts = client.get(f"/api/v1/sessions/{session_id}/artifacts").json()["artifacts"]
    va = next((a for a in artifacts if a["stage"] == "va"), None)
    assert va is not None and va["kind"] == "stats", artifacts
    resp = client.get(f"/api/v1/sessions/{session_id}/artifacts/va")
    assert resp.status_code == 200, resp.text
    stats = json.loads(resp.json()["content"])
    assert stats["raise_up_count"] == 5
    # A live source has no length to record.
    assert "duration_sec" not in stats


# A file source's length is recorded, as the UI's /store-video-duration does,
# so the report has a video duration to fall back on.
def test_va_records_file_video_duration(client, tmp_path, monkeypatch):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"\x00")
    probed = []

    def fake_probe(path):
        probed.append(path)
        return 1800.04

    monkeypatch.setattr("components.ffmpeg.audio_preprocessing.get_audio_duration", fake_probe)
    data, client = _create(client, ["va"], video_sources={"front": str(video)})
    state, _ = _await_status(client, data["session_id"])
    assert state == "completed"

    resp = client.get(f"/api/v1/sessions/{data['session_id']}/artifacts/va")
    assert resp.status_code == 200, resp.text
    assert json.loads(resp.json()["content"])["duration_sec"] == 1800.0
    assert probed == [str(video)]


# Board OCR on a live content camera never ends by itself, so a finished va
# stage stops it rather than leaving it reading the camera.
def test_va_stops_board_ocr_on_live_content(client, _mock_orchestrator):
    data, client = _create(client, ["va"],
                           video_sources={"content": "rtsp://127.0.0.1:8554/board"})
    state, _ = _await_status(client, data["session_id"])
    assert state == "completed"
    _mock_orchestrator["start_ocr"].assert_called_once()
    _mock_orchestrator["stop_ocr"].assert_called_once_with(data["session_id"])


# On a file it finishes by itself once its frame backlog is drained; stopping
# it when va ends would drop the frames it has not read yet.
def test_va_leaves_board_ocr_on_file_content_to_finish(client, _mock_orchestrator, tmp_path):
    video = tmp_path / "board.mp4"
    video.write_bytes(b"\x00")
    data, client = _create(client, ["va"], video_sources={"content": str(video)})
    state, _ = _await_status(client, data["session_id"])
    assert state == "completed"
    _mock_orchestrator["start_ocr"].assert_called_once()
    _mock_orchestrator["stop_ocr"].assert_not_called()


# A single transcribe stage completes and all other stages stay skipped.
def test_transcribe_only(client, tmp_path):
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"RIFF")
    data, client = _create(client, ["transcribe"], audio_path=str(audio))
    state, status = _await_status(client, data["session_id"])
    assert state == "completed"
    assert status["stages"]["transcribe"] == "done"
    for stage, val in status["stages"].items():
        if stage != "transcribe":
            assert val == "skipped", f"{stage} should be skipped, got {val}"


# Multiple audio stages run serially, each reaching done.
def test_multiple_stages_serial(client, tmp_path):
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"RIFF")
    data, client = _create(client, ["transcribe", "summarize", "mindmap"],
                           audio_path=str(audio))
    state, status = _await_status(client, data["session_id"])
    assert state == "completed"
    assert status["stages"]["transcribe"] == "done"
    assert status["stages"]["summarize"] == "done"
    assert status["stages"]["mindmap"] == "done"


# A pure VA session completes on its own.
def test_va_only(client):
    data, client = _create(client, ["va"],
                           video_sources={"front": "rtsp://127.0.0.1:8554/live"})
    state, status = _await_status(client, data["session_id"])
    assert state == "completed"
    assert status["stages"]["va"] == "done"


# va then segmentation: segmentation waits for the VA thread to finish first.
def test_va_then_segmentation(client, _mock_orchestrator):
    data, client = _create(client, ["va", "segmentation"],
                           video_sources={"front": "rtsp://127.0.0.1:8554/live"})
    session_id = data["session_id"]
    state, status = _await_status(client, session_id)
    assert state == "completed"
    assert status["stages"]["va"] == "done"
    assert status["stages"]["segmentation"] == "done"


# All six stages in one session all complete.
def test_all_stages(client, tmp_path):
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"RIFF")
    data, client = _create(
        client,
        ["transcribe", "summarize", "mindmap", "va", "segmentation", "report"],
        audio_path=str(audio),
        video_sources={"front": "rtsp://127.0.0.1:8554/live"},
    )
    state, status = _await_status(client, data["session_id"])
    assert state == "completed"
    for stage in ("transcribe", "summarize", "mindmap", "va", "segmentation", "report"):
        assert status["stages"][stage] == "done", f"{stage} should be done"


# Response body carries a well-formed session_id, absolute output dir and start time.
def test_response_shape(client, tmp_path):
    audio = tmp_path / "lecture.wav"
    audio.write_bytes(b"RIFF")
    data, client = _create(client, ["transcribe"], audio_path=str(audio))
    assert _SESSION_ID_RE.match(data["session_id"])
    assert data["output_dir"] and __import__("os").path.isabs(data["output_dir"])
    assert data["started_at"]
    wait_for_state(client, data["session_id"], timeout=5.0)

# The UI names the content camera "board"; /process launches it as the content
# pipeline (and so starts board OCR) rather than failing that launch silently.
def test_board_video_source_runs_the_content_pipeline(client, _mock_orchestrator):
    data, client = _create(client, ["va"], video_sources={
        "front": "rtsp://127.0.0.1:8554/front", "board": "rtsp://127.0.0.1:8554/board"})
    state, status = _await_status(client, data["session_id"])
    assert state == "completed" and status["stages"]["va"] == "done"
    launched = [c.args[0] for c in _mock_orchestrator["va_service"].launch_pipeline.call_args_list]
    assert sorted(launched) == ["content", "front"]
