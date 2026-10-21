from unittest.mock import patch

import pytest

from utils.stage_tracker import stage_tracker


def test_success_writes_done_event():
    with patch("utils.stage_tracker.StageEventWriter.write") as mw:
        with stage_tracker("s1", "summarize"):
            pass
    assert mw.called
    args, kwargs = mw.call_args
    # positional: session_id, stage, status, started_at, ended_at, duration
    assert args[0] == "s1"
    assert args[1] == "summarize"
    assert args[2] == "done"
    assert args[5] >= 0  # duration
    assert kwargs.get("error_class") is None


def test_failure_writes_failed_event_and_reraises():
    raised = False
    with patch("utils.stage_tracker.StageEventWriter.write") as mw:
        try:
            with stage_tracker("s1", "mindmap"):
                raise ValueError("boom")
        except ValueError:
            raised = True
    assert raised  # exception propagated
    args, kwargs = mw.call_args
    assert args[2] == "failed"
    assert kwargs.get("error_class") == "ValueError"
    assert kwargs.get("error_detail") == "boom"


def test_generator_exit_is_recorded_as_interrupted():
    """A client hanging up mid-stream closes the generator, raising GeneratorExit
    at the yield. It is not an Exception, so without its own branch the stage
    would be left at 'running'."""
    def streamer():
        with stage_tracker("s1", "transcribe"):
            yield "chunk"
            yield "never reached"

    with patch("utils.stage_tracker.StageEventWriter.write") as mw:
        gen = streamer()
        assert next(gen) == "chunk"
        gen.close()

    args, kwargs = mw.call_args
    assert args[2] == "interrupted"
    assert kwargs.get("error_class") == "GeneratorExit"


def test_keyboard_interrupt_is_recorded_and_reraised():
    with patch("utils.stage_tracker.StageEventWriter.write") as mw:
        with pytest.raises(KeyboardInterrupt):
            with stage_tracker("s1", "report"):
                raise KeyboardInterrupt
    assert mw.call_args[0][2] == "interrupted"


def test_handle_fail_records_failure_without_raising():
    """Streaming endpoints turn their errors into a payload rather than raising;
    StageHandle.fail() is how the tracker still hears about it."""
    with patch("utils.stage_tracker.StageEventWriter.write") as mw:
        with stage_tracker("s1", "report") as stage:
            stage.fail(RuntimeError("[ERROR]: no transcript"))

    args, kwargs = mw.call_args
    assert args[2] == "failed"
    assert kwargs.get("error_class") == "RuntimeError"
    assert kwargs.get("error_detail") == "[ERROR]: no transcript"


def test_stage_transitions_reach_the_session_store():
    with patch("utils.stage_tracker.StageEventWriter.write"), patch(
        "utils.stage_tracker.SessionStore.set_stage"
    ) as mset:
        with stage_tracker("s1", "summarize"):
            pass
    assert [c.args for c in mset.call_args_list] == [
        ("s1", "summarize", "running"),
        ("s1", "summarize", "done"),
    ]


def test_store_failure_does_not_break_the_stage():
    """Bookkeeping must never be able to fail a stage that actually succeeded."""
    with patch("utils.stage_tracker.StageEventWriter.write"), patch(
        "utils.stage_tracker.SessionStore.set_stage", side_effect=RuntimeError("db gone")
    ):
        with stage_tracker("s1", "summarize"):
            pass  # no exception escapes


def test_shutdown_records_a_running_stage_once():
    """VA runs inside stage_tracker on a daemon thread; at interpreter exit that
    thread is frozen mid-stage, so shutdown must write the record for it."""
    from utils.stage_tracker import close_open_stages

    with patch("utils.stage_tracker.StageEventWriter.write") as mw, patch(
        "utils.stage_tracker.SessionStore.set_stage"
    ):
        with stage_tracker("s1", "va"):
            assert close_open_stages() == 1
            args, kwargs = mw.call_args
            assert args[1:3] == ("va", "interrupted") and args[3] is not None
            assert args[5] >= 0 and kwargs.get("error_class") == "Shutdown"
        # The stage's own end, arriving later, does not add a second record.
        assert mw.call_count == 1
        assert close_open_stages() == 0


def test_shutdown_closes_a_manually_opened_stage_once():
    """The UI's VA stage spans two endpoints (stage_started/stage_finished)."""
    from utils.stage_tracker import close_open_stages, stage_finished, stage_started

    with patch("utils.stage_tracker.StageEventWriter.write") as mw, patch(
        "utils.stage_tracker.SessionStore.set_stage"
    ):
        stage_started("s2", "va")
        assert close_open_stages() == 1
        stage_finished("s2", "va", "failed")  # e.g. the atexit cleanup ending VA
        assert [c.args[2] for c in mw.call_args_list] == ["interrupted"]
        # A new attempt of the same stage records normally again.
        stage_started("s2", "va")
        stage_finished("s2", "va", "done")
        assert [c.args[2] for c in mw.call_args_list] == ["interrupted", "done"]


def test_a_stage_that_never_started_is_still_recorded():
    from utils.stage_tracker import stage_finished

    with patch("utils.stage_tracker.StageEventWriter.write") as mw, patch(
        "utils.stage_tracker.SessionStore.set_stage"
    ):
        stage_finished("s3", "va", "failed", error_detail="no pipeline launched")
    args, kwargs = mw.call_args
    assert args[2] == "failed" and args[3] is None and args[5] is None


def test_a_side_stage_is_recorded_but_never_reaches_the_session_row():
    """Board OCR is no declared session stage; mirroring it would make it the
    session's current_stage."""
    with patch("utils.stage_tracker.StageEventWriter.write") as mw, patch(
        "utils.stage_tracker.SessionStore.set_stage"
    ) as mset:
        with stage_tracker("s4", "board_ocr"):
            pass
    assert mw.call_args.args[1:3] == ("board_ocr", "done")
    assert not mset.called
