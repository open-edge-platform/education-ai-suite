# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""components.ffmpeg.audio_preprocessing: chunk files are shared, cleanup is not.

The chunk directory is shared by every process started from the app root. Its
exit cleanup once removed the whole directory, so any other process importing
the module (a test run, a second instance) deleted it under a running backend,
whose next chunks then failed to write and transcribed as empty text.
"""

from components.ffmpeg import audio_preprocessing as ap


def test_exit_cleanup_removes_only_this_processes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "CHUNKS_DIR", str(tmp_path))
    monkeypatch.setattr(ap, "CLEAN_UP_ON_EXIT", True)
    monkeypatch.setattr(ap, "_OWN_CHUNK_FILES", set())
    own = tmp_path / "chunk_0_aaaaaa.wav"
    foreign = tmp_path / "chunk_0_bbbbbb.wav"  # the running backend's
    own.write_bytes(b"x")
    foreign.write_bytes(b"x")
    ap._own_chunk_file(str(own))

    ap.cleanup_chunks_folder()
    assert not own.exists() and foreign.exists() and tmp_path.is_dir()

    foreign.unlink()
    ap.cleanup_chunks_folder()  # nothing left: the directory goes too
    assert not tmp_path.exists()


def test_a_chunk_ffmpeg_could_not_write_is_an_error(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(ap, "CHUNKS_DIR", str(tmp_path / "chunks"))  # missing: recreated
    with pytest.raises(RuntimeError, match="ffmpeg could not cut audio chunk 0"):
        ap.process_audio_segment(str(tmp_path / "missing.wav"), 0.0, 1.0, 0)
    assert (tmp_path / "chunks").is_dir()
