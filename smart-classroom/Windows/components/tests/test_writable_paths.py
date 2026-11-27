# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""An installed app writes only under its user data folder.

The backend runs with the program folder as its working folder. Installed for
every user, that is Program Files, which the unelevated app cannot write, so
nothing it creates at runtime may land there: audio chunks, MediaMTX, the
GStreamer plugin registry cache, or the YOLO download and export.
"""

import os
import sys
from pathlib import Path

import pytest

_SC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _SC_ROOT not in sys.path:
    sys.path.insert(0, _SC_ROOT)

from utils import data_dirs


def test_relative_paths_go_to_the_user_data_folder_when_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("SMART_CLASSROOM_USERDATA", str(tmp_path))
    assert data_dirs.writable_path("chunks/") == tmp_path / "chunks"
    assert data_dirs.writable_path(Path("storage") / "gstreamer" / "registry.bin") == \
        tmp_path / "storage" / "gstreamer" / "registry.bin"
    # A path someone chose on purpose is kept.
    absolute = tmp_path.parent / "elsewhere"
    assert data_dirs.writable_path(absolute) == absolute


def test_a_source_checkout_keeps_its_paths(monkeypatch):
    monkeypatch.delenv("SMART_CLASSROOM_USERDATA", raising=False)
    assert data_dirs.writable_path("chunks/") == Path("chunks/")
    monkeypatch.setenv("SMART_CLASSROOM_USERDATA", "  ")
    assert data_dirs.writable_path("chunks/") == Path("chunks/")


def test_the_gstreamer_registry_cache_is_user_data(tmp_path, monkeypatch):
    from utils import gstreamer_env

    monkeypatch.setenv("SMART_CLASSROOM_USERDATA", str(tmp_path))
    monkeypatch.delenv("GST_REGISTRY", raising=False)
    gstreamer_env.ensure_gst_registry()
    assert Path(os.environ["GST_REGISTRY"]) == (tmp_path / "storage" / "gstreamer" / "registry.bin").resolve()
    assert (tmp_path / "storage" / "gstreamer").is_dir()


class _Loaded(Exception):
    pass


def test_the_yolo_model_downloads_into_its_output_folder(tmp_path, monkeypatch):
    """Not the working folder: ultralytics downloads to the path it is given,
    and exports next to it."""
    from utils import convert_yolo_models

    seen = []

    def fake_yolo(path):
        seen.append(Path(path))
        raise _Loaded

    monkeypatch.setattr(convert_yolo_models, "YOLO", fake_yolo)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "models" / "va"
    with pytest.raises(_Loaded):
        convert_yolo_models.convert_yolo_to_openvino("yolov8m-pose", str(out))
    assert seen == [out / "yolov8m-pose.pt"]
    assert not list(tmp_path.glob("*.pt"))


def test_the_session_database_lives_with_the_sessions(tmp_path, monkeypatch):
    from utils.session_paths import SessionPaths
    from utils.session_store import SessionStore

    monkeypatch.setenv("SMART_CLASSROOM_USERDATA", str(tmp_path))
    db = Path(SessionStore._db_path())
    assert db.parent == SessionPaths.base_dir()
    assert tmp_path in db.parents


def test_mediamtx_downloads_beside_its_folder_not_into_the_working_folder(tmp_path, monkeypatch):
    import io
    import logging
    import zipfile

    from components.va import media_service

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("mediamtx.exe", b"exe")
        zf.writestr("mediamtx.yml", "rtpAddress: :8000\nrtcpAddress: :8001\n")

    class Response:
        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield archive.getvalue()

    monkeypatch.setattr(media_service.requests, "get", lambda *a, **k: Response())
    work = tmp_path / "program"
    work.mkdir()
    monkeypatch.chdir(work)

    service = media_service.MediaService.__new__(media_service.MediaService)
    service.logger = logging.getLogger("test")
    # A folder whose parents do not exist yet, as in a new user data folder.
    service.mediamtx_dir = tmp_path / "ud" / "components" / "va" / "bin" / "mediamtx"
    service._download_mediamtx()

    assert (service.mediamtx_dir / "mediamtx.exe").read_bytes() == b"exe"
    assert "rtpAddress: :8500" in (service.mediamtx_dir / "mediamtx.yml").read_text(encoding="utf-8")
    assert not list(work.iterdir())
    assert not (service.mediamtx_dir.parent / "mediamtx.zip").exists()
