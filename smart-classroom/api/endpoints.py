from fastapi import UploadFile
from fastapi.responses import JSONResponse
from fastapi import APIRouter, FastAPI
from dto.transcription_dto import TranscriptionRequest
from dto.summarizer_dto import SummaryRequest
from pipeline import Pipeline
import json
from fastapi.responses import StreamingResponse

router = APIRouter()
pipeline = Pipeline(None)

@router.post("/upload")
async def upload_audio(file: UploadFile):
    return JSONResponse(content={"status": "success", "message": "Audio upload placeholder"})

@router.post("/transcribe")
async def transcribe_audio(request: TranscriptionRequest):
    audio_path = request.audio_filename

    def stream_transcription():
        for chunk_data in pipeline.run_transcription(audio_path):
            yield json.dumps(chunk_data) + "\n"

    return StreamingResponse(stream_transcription(), media_type="application/json")

@router.post("/summarize")
async def summarize_audio(request: SummaryRequest):
    return JSONResponse(content={"status": "success", "summary": "Summary placeholder"})

def register_routes(app: FastAPI):
    app.include_router(router)
