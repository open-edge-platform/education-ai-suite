"""Video upload persistence for Video Analytics.

Saves the clip into the per-session VA dir in the shared ``storage`` volume. The
side-car mounts that volume at the same path, so it reads the uploaded file at
the absolute path we return — no client-supplied host path is ever trusted.
"""
import logging
import os
import re
from typing import Tuple

from fastapi import HTTPException, UploadFile

from utils.config_loader import config
from utils.session_paths import SessionPaths

logger = logging.getLogger(__name__)

# Conservative default caps; overridable via a `video_util:` config block.
_DEFAULT_ALLOWED_EXTENSIONS = (".mp4", ".avi", ".mkv", ".mov", ".webm")
_DEFAULT_MAX_SIZE_MB = 4096
_DEFAULT_CHUNK_SIZE = 50 * 1024 * 1024

_VALID_PIPELINES = ("front", "back", "content")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _cfg(attr: str, default):
    vu = getattr(config, "video_util", None)
    return getattr(vu, attr, default) if vu is not None else default


def _allowed_extensions() -> Tuple[str, ...]:
    exts = _cfg("allowed_extensions", None)
    if not exts:
        return _DEFAULT_ALLOWED_EXTENSIONS
    return tuple(str(e).lower() for e in exts)


def _sanitize(filename: str) -> str:
    """Reduce an upload filename to a safe basename (no path components)."""
    base = os.path.basename(filename or "")
    base = base.replace("\\", "/").split("/")[-1]
    safe = _SAFE_NAME.sub("_", base).lstrip(".") or "video"
    return safe


def save_video_file(
    file: UploadFile, session_id: str, pipeline_name: str
) -> Tuple[str, str]:
    """Persist an uploaded video into ``<session>/raw/va/uploads`` and return
    ``(filename, absolute_path)``. The path is valid inside both the app and the
    video-analytics containers (shared storage volume, common ``/app`` WORKDIR).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    if pipeline_name not in _VALID_PIPELINES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid pipeline_name '{pipeline_name}'. "
            f"Must be one of: {list(_VALID_PIPELINES)}",
        )

    allowed = _allowed_extensions()
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Allowed: {', '.join(allowed)}",
        )

    max_size_bytes = int(_cfg("max_size_mb", _DEFAULT_MAX_SIZE_MB)) * 1024 * 1024
    chunk_size = int(_cfg("chunk_size", _DEFAULT_CHUNK_SIZE))

    uploads_dir = SessionPaths.va_dir(session_id) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    # Name the file by pipeline so re-uploading one camera never collides with
    # another, and the source is self-describing in logs.
    safe_name = f"{pipeline_name}__{_sanitize(file.filename)}"
    dest = (uploads_dir / safe_name).resolve()

    total = 0
    with open(dest, "wb") as out:
        while True:
            chunk = file.file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_size_bytes:
                out.close()
                try:
                    os.remove(dest)
                except OSError:
                    pass
                raise HTTPException(status_code=400, detail="File too large")
            out.write(chunk)
    try:
        file.file.seek(0)
    except Exception:  # noqa: BLE001 - best-effort rewind
        pass

    if total == 0:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Empty upload")

    logger.info("[VA] saved uploaded video: %s (%d bytes)", dest, total)
    return safe_name, str(dest)
