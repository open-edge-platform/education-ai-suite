import asyncio
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import Header, UploadFile
from fastapi.responses import JSONResponse, FileResponse
from fastapi import APIRouter, FastAPI, File, HTTPException, Request, status
from dto.transcription_dto import TranscriptionRequest
from dto.summarizer_dto import SummaryRequest
from dto.video_metadata_dto import VideoDurationRequest
from pipeline import Pipeline
import json, os, time
import subprocess, re
from fastapi.responses import StreamingResponse
from utils.runtime_config_loader import RuntimeConfig
from utils.storage_manager import StorageManager
from utils.session_paths import SessionPaths
from utils.platform_info import get_platform_and_model_info
from dto.project_settings import ProjectSettings
from monitoring.monitor import get_metrics
from dto.audiosource import AudioSource
from components.ffmpeg import audio_preprocessing
from utils.audio_util import save_audio_file
from utils.session_manager import generate_session_id
from dto.search_dto import SearchRequest
from utils.session_state_manager import SessionState
from dto.ocr_dto import OCRExtractRequest, OCRResponse
from components.ocr.ocr_pipeline import ocr_detect_file, ocr_extract_text

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/health")
def health():
    from model_manager import ModelManager
    hub = ModelManager.instance().health()
    return JSONResponse(content={"status": "ok", "hub": hub}, status_code=200)

@router.get("/create-session")
def create_session():
    return JSONResponse(content={"session-id":  generate_session_id()}, status_code=200)

@router.get("/features")
def get_features(request: Request):
    """Return enabled features with full UI descriptors for dynamic frontend rendering."""
    from model_manager.features import in_dependency_order

    eff = getattr(request.app.state, "features", None)
    if eff is None:
        return JSONResponse(
            content={"features": []},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    features = []
    for feature in in_dependency_order():
        if not eff.is_enabled(feature.id):
            continue
        
        # Merge basic metadata with ui_descriptor for complete feature config
        descriptor = feature.ui_descriptor()
        descriptor["dependency"] = list(feature.depends_on)
        descriptor["requires"] = list(feature.requires)
        features.append(descriptor)

    return JSONResponse(
        content={"features": features},
        status_code=status.HTTP_200_OK,
    )


@router.get("/performance-metrics")
def get_summary_metrics(session_id: Optional[str] = Header(None, alias="session_id")):
    project_config = RuntimeConfig.get_section("Project")
    location = project_config.get("location")
    name = project_config.get("name")

    if not session_id:
        return JSONResponse(
            content={"error": "Missing required header: session_id"},
            status_code=status.HTTP_400_BAD_REQUEST
        )
    if not location or not name:
        return JSONResponse(
            content={"error": "Missing project configuration for 'location' or 'name'"},
            status_code=status.HTTP_400_BAD_REQUEST
        )

    try:
        nested_metrics = StorageManager.read_performance_metrics(location, name, session_id)
        return JSONResponse(
            content=nested_metrics,
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Error reading performance metrics: {e}")
        return JSONResponse(
            content={"error": "Error reading performance metrics"},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@router.get("/project")
def get_project_config():
    return RuntimeConfig.get_section("Project")

@router.post("/project")
def update_project_config(payload: ProjectSettings):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    return RuntimeConfig.update_section("Project", updates)

@router.get("/metrics")
def get_metrics_endpoint():
    return get_metrics()

@router.get("/platform-info")
def get_platform_info():
    try:
        info = get_platform_and_model_info()
        return JSONResponse(content=info, status_code=200)
    except Exception as e:
        logger.error(f"Error fetching platform info: {e}")
        return JSONResponse(content={"error": "Error fetching platform info"}, status_code=500)

@router.post("/mark-video-usage")
def mark_video_usage(
    session_id: str = Header(None, alias="X-Session-ID")
):
    """
    Mark that a video is being used in the current session.

    """
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="X-Session-ID header is required"
        )
    
    try:
        with SessionState._lock:
            if session_id not in SessionState._sessions:
                SessionState._sessions[session_id] = {}
            SessionState._sessions[session_id]['has_video'] = True
        
        logger.info(f"Session {session_id}: Video usage marked")
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": "Video usage marked for session"}
        )
        
    except Exception as e:
        logger.error(f"Session {session_id}: Error marking video usage: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error marking video usage: {e}"
        )

@router.post("/store-video-duration")
def store_video_duration(
    request: VideoDurationRequest,
    session_id: str = Header(None, alias="X-Session-ID")
):
    """
    Store video duration 

    """
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="X-Session-ID header is required"
        )
    
    try:
        duration = request.duration
        
        if not duration or duration <= 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid duration: duration must be greater than 0"
            )
        
        # Store the video duration in session state
        SessionState.set_video_duration(session_id, duration)
        
        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": f"Video duration stored: {duration:.2f}s"}
        )
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Session {session_id}: Error storing video duration: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error storing video duration: {e}"
        )

@router.post("/store-audio-duration")
def store_audio_duration(
    request: VideoDurationRequest,
    session_id: str = Header(None, alias="X-Session-ID")
):
    """
    Store audio duration 

    """
    
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="X-Session-ID header is required"
        )
    
    try:
        duration = request.duration
        
        if not duration or duration <= 0:
            raise HTTPException(
                status_code=400,
                detail="Invalid duration: duration must be greater than 0"
            )
        
        SessionState.set_audio_duration(session_id, duration)

        with SessionState._lock:
            if session_id not in SessionState._sessions:
                SessionState._sessions[session_id] = {}
            SessionState._sessions[session_id]['has_audio'] = True

        return JSONResponse(
            status_code=200,
            content={"status": "success", "message": f"Audio duration stored: {duration:.2f}s"}
        )
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Session {session_id}: Error storing audio duration: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error storing audio duration: {e}"
        )

@router.post("/search-content")
def search_content(request: SearchRequest):

    pipeline = Pipeline(request.session_id)

    try:
        results = pipeline.search_content(
            query=request.query,
            top_k=request.top_k
        )

        return {
            "session_id": request.session_id,
            "query": request.query,
            "results": results
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {e}"
        )

@router.get("/check-recorded-videos")
def check_recorded_videos(x_session_id: Optional[str] = Header(None)):
    """
    Check which video files were saved for a session after RTSP recording.
    Returns the priority-ordered available video (back > board > front).

    """
    if not x_session_id:
        raise HTTPException(
            status_code=400, detail="Missing required header: x-session-id"
        )
    
    try:
        project_config = RuntimeConfig.get_section("Project")
        base_path = os.path.join(
            project_config.get("location"),
            project_config.get("name"),
            x_session_id
        )
        
        if not os.path.exists(base_path):
            logger.warn(f"Session path does not exist: {base_path}")
            return JSONResponse(
                content={
                    "session_id": x_session_id,
                    "back": None,
                    "board": None,
                    "front": None,
                    "selected_video": None,
                    "message": "No session path found"
                },
                status_code=200
            )
        
        # Check which videos exist
        videos = {
            "back": None,
            "board": None, 
            "front": None,
        }
        
        back_path = os.path.join(base_path, "back.mp4")
        content_path = os.path.join(base_path, "content.mp4") 
        front_path = os.path.join(base_path, "front.mp4")
        
        if os.path.exists(back_path):
            videos["back"] = back_path
        if os.path.exists(content_path):
            videos["board"] = content_path  
        if os.path.exists(front_path):
            videos["front"] = front_path
        
        # Select highest priority video (back > board > front)
        selected_video = None
        if videos["back"]:
            selected_video = "back"
        elif videos["board"]:
            selected_video = "board"
        elif videos["front"]:
            selected_video = "front"
        
        return JSONResponse(
            content={
                "session_id": x_session_id,
                "back": videos["back"],
                "board": videos["board"],
                "front": videos["front"],
                "selected_video": selected_video,
                "selected_path": videos[selected_video] if selected_video else None
            },
            status_code=200
        )
        
    except Exception as e:
        logger.error(f"Error checking recorded videos: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recorded-video/{videoType}")
def get_recorded_video(videoType: str, x_session_id: Optional[str] = Header(None), session_id: Optional[str] = None):
    """
    Stream a recorded video file (back.mp4, board.mp4, or front.mp4).

    """
    # Accept session ID from either header or query parameter
    actual_session_id = x_session_id or session_id
    if not actual_session_id:
        raise HTTPException(
            status_code=400, detail="Missing required session ID: x-session-id header or ?session_id query parameter"
        )
    
    if videoType not in ['back', 'board', 'front']:
        raise HTTPException(
            status_code=400, detail=f"Invalid videoType: {videoType}. Must be 'back', 'board', or 'front'"
        )
    
    try:
        backend_video_type = "content" if videoType == "board" else videoType
        
        project_config = RuntimeConfig.get_section("Project")
        video_path = os.path.join(
            project_config.get("location"),
            project_config.get("name"),
            actual_session_id,
            f"{backend_video_type}.mp4"
        )
        
        if not os.path.exists(video_path):
            raise HTTPException(
                status_code=404, 
                detail=f"Video file not found: {videoType}.mp4"
            )
        
        logger.info(f"Serving video file: {video_path} for session {actual_session_id}")
        
        file_response = FileResponse(
            path=video_path,
            media_type="video/mp4",
            filename=f"{videoType}.mp4"
        )
        file_response.headers["Accept-Ranges"] = "bytes"
        file_response.headers["Access-Control-Allow-Origin"] = "*"
        file_response.headers["Cache-Control"] = "no-cache"
        
        return file_response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving recorded video: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/ocr/detect-file", response_model=OCRResponse)
def ocr_detect_file_endpoint(file: UploadFile = File(...)):
    return ocr_detect_file(file)


@router.post("/ocr/extract-text", response_model=OCRResponse)
def ocr_extract_text_endpoint(file: UploadFile = File(...), x_session_id: Optional[str] = Header(None)):
    return ocr_extract_text(file, x_session_id)

def register_routes(app: FastAPI):
    app.include_router(router)

    from api.v1.api import v1_router
    app.include_router(v1_router, prefix="/api/v1")

    from api.vlm_chat import router as vlm_chat_router
    app.include_router(vlm_chat_router)
