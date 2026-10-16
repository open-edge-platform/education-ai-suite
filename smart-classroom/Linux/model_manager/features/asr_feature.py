import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from components.asr_remote import persist_live_segments
from dto.transcription_dto import TranscriptionRequest
from pipeline import Pipeline
from utils.audio_analyzer_client import AudioAnalyzerClient
from utils.audio_util import save_audio_file
from utils.config_loader import config

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
        return JSONResponse(
            status_code=he.status_code,
            content={"status": "error", "message": he.detail}
        )
    except Exception as e:
        logger.error(f"General exception occurred: {str(e)}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"status": "error", "message": "Failed to upload audio file"}
    )


@router.post("/transcribe")
def transcribe_audio(
    request: TranscriptionRequest,
    x_session_id: Optional[str] = Header(None)
):
    pipeline = Pipeline(x_session_id)

    def stream_transcription():
        for chunk_data in pipeline.run_transcription(request):
            yield json.dumps(chunk_data) + "\n"

    response = StreamingResponse(stream_transcription(), media_type="application/json")
    response.headers["X-Session-ID"] = pipeline.session_id
    return response


class LiveTranscriptRequest(BaseModel):
    session_id: str
    segments: List[dict]
    language: Optional[str] = None


@router.post("/live-transcript")
def persist_live_transcript(request: LiveTranscriptRequest):
    """Persist a browser live-mic transcript so downstream stages can read it.

    The realtime WebSocket path transcribes in the browser; this writes the
    finalized segments into the session's transcript files (with TEACHER/STUDENT
    mapping), mirroring what the file-upload path produces.
    """
    if not request.segments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No transcript segments provided.",
        )
    result = persist_live_segments(request.session_id, request.segments, request.language)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)


class ASRFeature:
    """F1 transcription exposed as a FeatureModule.

    Transcription is served out-of-process by the audio-analyzer microservice,
    so this feature declares no in-process capability requirement; it only
    verifies the service is reachable at build time.
    """

    id: str = "asr"
    requires: List[str] = []
    depends_on: List[str] = []
    router: APIRouter = router

    def __init__(self) -> None:
        self._client: Optional[AudioAnalyzerClient] = None

    def build(self) -> None:
        self._client = AudioAnalyzerClient()
        if self._client.health():
            logger.info("ASRFeature built; audio-analyzer reachable at %s.", self._client.base_url)
        else:
            logger.warning(
                "ASRFeature built but audio-analyzer is not reachable at %s yet; "
                "transcription will fail until the service is up.",
                self._client.base_url,
            )

    def teardown(self) -> None:
        self._client = None
        logger.info("ASRFeature torn down.")

    def ui_descriptor(self) -> Dict:
        return {
            "id": self.id,
            "chunking": bool(config.audio_preprocessing.chunking),
            "diarization": bool(config.models.asr.diarization),
            "endpoints": {
                "upload_audio": "/upload-audio",
                "transcribe": "/transcribe",
            },
        }
