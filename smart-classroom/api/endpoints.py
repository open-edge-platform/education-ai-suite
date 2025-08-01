from fastapi import UploadFile
from fastapi.responses import JSONResponse
from fastapi import APIRouter, FastAPI
from dto.transcription_dto import TranscriptionRequest
from dto.summarizer_dto import SummaryRequest

router = APIRouter()

@router.post("/upload")
async def upload_audio(file: UploadFile):
    return JSONResponse(content={"status": "success", "message": "Audio upload placeholder"})

@router.post("/transcribe")
async def transcribe_audio(request: TranscriptionRequest):
    #Pass Transcription Request with audio file path, model id
    return JSONResponse(content={"status": "success", "transcription": "Transcription placeholder"})

@router.post("/summarize")
async def summarize_audio(request: SummaryRequest):
    return JSONResponse(content={"status": "success", "summary": "Summary placeholder"})

def register_routes(app: FastAPI):
    app.include_router(router)
