from pydantic import BaseModel

# Request DTOs
class TranscriptionRequest(BaseModel):
    audio_filename: str
