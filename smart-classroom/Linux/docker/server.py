# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
#
# Lightweight UI-serving skeleton for the Smart Classroom container.
#
# Serves the built React SPA (``ui/dist``) plus ``/health``, ``/metrics``, and
# ``/platform-info`` (proxied straight to the metrics-collector sidecar via
# monitoring/monitor.py) WITHOUT importing the heavy model stack
# (torch/openvino/paddleocr/...). It exists for the containerization skeleton
# phase, where the OVMS, model-downloader, and content-search containers are
# not yet built, so the app image can boot, render the UI, and show the live
# Resource Utilization dashboard on its own.
#
# Once the full backend image is wired up, swap the container CMD from
# ``uvicorn skeleton_server:app`` to ``uvicorn main:app`` and drop this module
# from the runtime stage.

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, JSONResponse

from monitoring.monitor import get_metrics, get_platform_info

# Directory holding the Vite build. Defaults to ``<this dir>/ui/dist`` so it
# matches the layout baked into the image; override with ``UI_DIST_DIR``.
UI_DIST = Path(
    os.environ.get("UI_DIST_DIR", Path(__file__).resolve().parent / "ui" / "dist")
)

app = FastAPI(title="Smart Classroom (UI skeleton)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    """Backend liveness probe the SPA pings at ``/health``."""
    return JSONResponse({"status": "ok", "mode": "ui-skeleton"})


@app.get("/metrics", include_in_schema=False)
async def metrics() -> JSONResponse:
    """Live Resource Utilization dashboard data, proxied from metrics-collector.

    Session-less here (unlike the full backend's /metrics): the sidecar's
    collectors run continuously regardless of session state, so there is no
    session-scoped variant to serve in the skeleton phase.
    """
    return JSONResponse(get_metrics())


@app.get("/platform-info", include_in_schema=False)
async def platform_info() -> JSONResponse:
    """Hardware summary, proxied from metrics-collector.

    Skips the full backend's asr_model/summarizer_model merge (utils/platform_info.py)
    since no models are loaded in the skeleton phase.
    """
    return JSONResponse(get_platform_info())


def _mount_spa() -> None:
    """Serve the built SPA with an index.html fallback for client-side routes."""
    index_file = UI_DIST / "index.html"
    if not index_file.is_file():
        # No build present (e.g. running the module outside the image): expose
        # only /health so the container still starts and stays diagnosable.
        return

    assets_dir = UI_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    dist_root = UI_DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # Serve a real build file when it exists (favicon, manifest, ...),
        # otherwise fall back to index.html for client-side routing / refresh.
        candidate = (dist_root / full_path).resolve()
        if candidate.is_file() and str(candidate).startswith(str(dist_root)):
            return FileResponse(str(candidate))
        return FileResponse(str(index_file))


# --- Transcription endpoints (delegated to the audio-analyzer microservice) ---
#
# The heavy model stack (summary/mindmap/VA/OCR) is NOT loaded here; transcription
# is served out-of-process by the audio-analyzer, so these endpoints only need the
# lightweight client + speaker-mapping layer. Wrapped in try/except so a config or
# wiring problem can never take down the UI + /health the container is built to serve.
try:
    import json as _json
    from typing import List as _List, Optional as _Optional

    from fastapi import File, Header, HTTPException, UploadFile, status
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel

    from api.proxy import register_realtime_ws_proxy
    from components.asr_remote import RemoteASRComponent, persist_live_segments
    from utils.audio_util import save_audio_file
    from utils.session_manager import generate_session_id

    class _TranscriptionRequest(BaseModel):
        audio_filename: str

    class _LiveTranscriptRequest(BaseModel):
        session_id: str
        segments: _List[dict]
        language: _Optional[str] = None

    @app.post("/upload-audio")
    def upload_audio(file: UploadFile = File(...)):
        """Persist an uploaded audio file so /transcribe can hand it to the service."""
        filename, filepath = save_audio_file(file)
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"filename": filename, "message": "File uploaded successfully", "path": filepath},
        )

    @app.post("/transcribe")
    def transcribe(request: _TranscriptionRequest, x_session_id: _Optional[str] = Header(None)):
        """Stream a transcription for an uploaded audio file via the audio-analyzer."""
        if not os.path.isfile(request.audio_filename):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Audio file not found.")
        session_id = x_session_id or generate_session_id()
        component = RemoteASRComponent(session_id)

        def _stream():
            for chunk in component.process(request.audio_filename):
                yield _json.dumps(chunk) + "\n"

        response = StreamingResponse(_stream(), media_type="application/json")
        response.headers["X-Session-ID"] = session_id
        return response

    @app.post("/live-transcript")
    def live_transcript(request: _LiveTranscriptRequest):
        """Persist a browser live-mic transcript into the session."""
        if not request.segments:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No transcript segments provided.")
        return persist_live_segments(request.session_id, request.segments, request.language)

    @app.get("/features", include_in_schema=False)
    def features() -> JSONResponse:
        """Advertise the transcription (audio) feature to the SPA.

        The skeleton only serves ASR (delegated to the audio-analyzer); the heavy
        features (summary/mindmap/video-analytics/OCR) need the full backend, so
        they are intentionally omitted here. The SPA's feature guard reads this to
        enable the recording/upload → transcribe path.
        """
        from utils.config_loader import config

        asr_flag = getattr(getattr(config, "features", None), "asr", True)
        if not bool(getattr(asr_flag, "enabled", asr_flag)):
            return JSONResponse({"features": []})
        try:
            chunking = bool(config.audio_preprocessing.chunking)
        except Exception:
            chunking = False
        try:
            diarization = bool(config.models.asr.diarization)
        except Exception:
            diarization = False
        return JSONResponse({"features": [{
            "id": "asr",
            "chunking": chunking,
            "diarization": diarization,
            "endpoints": {"upload_audio": "/upload-audio", "transcribe": "/transcribe"},
            "dependency": [],
            "requires": [],
        }]})

    @app.get("/create-session", include_in_schema=False)
    def create_session() -> JSONResponse:
        """Mint a session id for the SPA's upload/record → transcribe flow."""
        return JSONResponse({"session-id": generate_session_id()})

    @app.post("/store-audio-duration", include_in_schema=False)
    def store_audio_duration() -> JSONResponse:
        """Accept-and-ignore: duration tracking lives in the full backend."""
        return JSONResponse({"status": "ok", "message": "Audio duration not tracked in the UI skeleton."})

    # Browser live-mic: bridge the /v1/realtime WebSocket to the audio-analyzer.
    register_realtime_ws_proxy(app)
except Exception as _exc:  # noqa: BLE001 - keep UI + health serving even if ASR wiring fails
    import logging as _logging

    _logging.getLogger(__name__).warning("Transcription endpoints unavailable: %s", _exc)


_mount_spa()
