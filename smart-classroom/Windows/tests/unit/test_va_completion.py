import json
import threading

import pytest

from utils.session_paths import SessionPaths
from utils.session_state_manager import SessionState
from utils.va_completion import save_va_outputs, wait_for_va_completion


class FakeService:
    """Minimal stand-in for VideoAnalyticsPipelineService's completion surface."""

    def __init__(self, final_status=None, running=None):
        self.pipeline_final_status = dict(final_status or {})
        self._running = set(running or [])

    def is_pipeline_running(self, name):
        return name in self._running


def _wait(service, wanted, done=None, timeout=1.0, **kw):
    done = done if done is not None else threading.Event()
    final_status = {}
    ok = wait_for_va_completion(
        service, wanted, done, final_status, timeout, **kw
    )
    return ok, final_status


def test_done_event_returns_immediately():
    service = FakeService(running=["front"])
    done = threading.Event()
    done.set()
    ok, final_status = _wait(service, ["front"], done=done)
    assert ok is True


def test_all_final_status_eos_returns_true():
    service = FakeService(final_status={"front": "eos"}, running=["front"])
    ok, final_status = _wait(service, ["front"], timeout=0.2)
    assert ok is True
    assert final_status["front"] == "eos"


def test_any_final_status_failed_returns_true():
    service = FakeService(final_status={"front": "failed", "back": "eos"})
    ok, _ = _wait(service, ["front", "back"], timeout=0.2)
    assert ok is True


def test_all_processes_down_fallback_returns_true():
    service = FakeService(final_status={})  # nothing recorded
    ok, _ = _wait(service, ["front"], timeout=1.0, interval=0.01, grace_polls=2)
    assert ok is True


def test_running_until_timeout_returns_false():
    service = FakeService(running=["front"])
    ok, _ = _wait(service, ["front"], timeout=0.05, interval=0.01)
    assert ok is False


def test_final_status_refreshed_into_caller_dict():
    service = FakeService(final_status={"front": "eos"}, running=["front"])
    done = threading.Event()
    final_status = {"stale": True}
    ok = wait_for_va_completion(service, ["front"], done, final_status, 0.2)
    assert ok is True
    assert final_status == {"stale": True, "front": "eos"}


def test_brief_dip_does_not_complete_prematurely():
    """A pipeline that briefly drops then stays up must not complete via fallback."""
    service = FakeService(running=["front"])
    count = [0]

    def is_running(name):
        count[0] += 1
        if count[0] == 1:
            return False  # brief dip
        return True       # stays up

    service.is_pipeline_running = is_running
    # grace_polls=3 -> the single down tick never accumulates to 3, so it times out
    ok, _ = _wait(service, ["front"], timeout=0.3, interval=0.01, grace_polls=3)
    assert ok is False


# ---------------------------------------------------------------------------
# save_va_outputs
# ---------------------------------------------------------------------------
SESSION = "20260101-000000-beef"


class StatsService:
    """Stand-in exposing get_pose_stats only."""

    def __init__(self, stats=None, raises=None):
        self.stats = stats if stats is not None else {"student_count": 30, "raise_up_count": 5}
        self.raises = raises
        self.posture_files = []

    def get_pose_stats(self, front_posture_file, previous_state=None):
        self.posture_files.append(front_posture_file)
        if self.raises:
            raise self.raises
        return dict(self.stats), {}


@pytest.fixture(autouse=True)
def _no_senders(monkeypatch):
    monkeypatch.setattr("utils.scp_sender.get_scp_sender", lambda: None)
    monkeypatch.setattr("utils.telegram_sender.get_sender", lambda: None)


def test_save_va_outputs_writes_class_statistics():
    service = StatsService()
    stats = save_va_outputs(service, SESSION)

    assert stats == {"student_count": 30, "raise_up_count": 5}
    path = SessionPaths.class_statistics_path(SESSION)
    assert json.loads(path.read_text(encoding="utf-8")) == stats
    assert service.posture_files == [str(SessionPaths.va_dir(SESSION) / "front_posture.txt")]


def test_save_va_outputs_records_known_video_duration(monkeypatch):
    monkeypatch.setattr(SessionState, "get_video_duration", classmethod(lambda cls, sid: 3312.46))
    stats = save_va_outputs(StatsService(), SESSION)

    assert stats["duration_sec"] == 3312.5
    saved = json.loads(SessionPaths.class_statistics_path(SESSION).read_text(encoding="utf-8"))
    assert saved["duration_sec"] == 3312.5


def test_save_va_outputs_never_raises():
    assert save_va_outputs(StatsService(raises=RuntimeError("bad posture file")), SESSION) is None
    assert not SessionPaths.class_statistics_path(SESSION).exists()
