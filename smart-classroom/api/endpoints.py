from typing import Optional
from fastapi import Header, UploadFile
from fastapi.responses import JSONResponse
from fastapi import APIRouter, FastAPI, HTTPException
from dto.transcription_dto import TranscriptionRequest
from dto.summarizer_dto import SummaryRequest
from pipeline import Pipeline
import json
from fastapi.responses import StreamingResponse
from utils.runtime_config_loader import RuntimeConfig
from dto.project_settings import ProjectSettings
from app import start_monitoring, stop_monitoring
router = APIRouter()

@router.post("/upload")
async def upload_audio(file: UploadFile):
    return JSONResponse(content={"status": "success", "message": "Audio upload placeholder"})

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
async def start_monitoring_endpoint():
    start_monitoring()
    return JSONResponse(content={"status": "success", "message": "Monitoring started"})
 
@router.post("/stop-monitoring")
async def stop_monitoring_endpoint():
    stop_monitoring()
    return JSONResponse(content={"status": "success", "message": "Monitoring stopped"})
def register_routes(app: FastAPI):
    app.include_router(router)
