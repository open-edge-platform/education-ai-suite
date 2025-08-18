from typing import Optional
from fastapi import Header, UploadFile
from fastapi.responses import JSONResponse
from fastapi import APIRouter, FastAPI, File, HTTPException, status
from dto.transcription_dto import TranscriptionRequest
from dto.summarizer_dto import SummaryRequest
from pipeline import Pipeline
import json
from fastapi.responses import StreamingResponse
from utils.runtime_config_loader import RuntimeConfig
from dto.project_settings import ProjectSettings
from monitoring.monitor import start_monitoring, stop_monitoring, get_metrics
from utils.audio_util import save_audio_file
import logging
logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload-audio")
def upload_audio(file: UploadFile = File(...)):
    status_code = status.HTTP_201_CREATED
    try:
        filename, filepath = save_audio_file(file)
        return JSONResponse(
            status_code=status_code,
            content={
                "filename": filename,
                "message": "File uploaded successfully",
                "path": filepath
            }
        )
    except HTTPException as he:
        logger.error(f"HTTPException occurred: {he.detail}")
        status_code = he.status_code
    except Exception as e:
        logger.error(f"General exception occurred: {str(e)}")
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    
    return JSONResponse(
        status_code=status_code,
        content={"status": "error", "message": "Failed to upload audio file"}
    )


@router.post("/transcribe")
async def transcribe_audio(
    request: TranscriptionRequest,
    x_session_id: Optional[str] = Header(None)  # Accept custom header
):
    pipeline = Pipeline(x_session_id)
    audio_path = request.audio_filename

    def stream_transcription():
        for chunk_data in pipeline.run_transcription(audio_path):
            yield json.dumps(chunk_data) + "\n"

    response = StreamingResponse(stream_transcription(), media_type="application/json")
    response.headers["X-Session-ID"] = pipeline.session_id
    return response


@router.post("/summarize")
async def summarize_audio(request: SummaryRequest):
    return JSONResponse(content={"status": "success", "summary": "Summary placeholder"})

@router.get("/project")
def get_project_config():
    return RuntimeConfig.get_section("Project")

@router.post("/project")
def update_project_config(payload: ProjectSettings):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update.")
    return RuntimeConfig.update_section("Project", updates)

@router.post("/start-monitoring")
def start_monitoring_endpoint():
    start_monitoring()
    return JSONResponse(content={"status": "success", "message": "Monitoring started"})

@router.get("/metrics")
def get_metrics_endpoint(x_session_id: Optional[str] = Header(None)):
    return get_metrics()

@router.post("/stop-monitoring")
def stop_monitoring_endpoint():
    stop_monitoring()
    return JSONResponse(content={"status": "success", "message": "Monitoring stopped"})

def register_routes(app: FastAPI):
    app.include_router(router)
