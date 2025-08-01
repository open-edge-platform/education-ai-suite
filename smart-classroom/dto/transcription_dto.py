from pydantic import BaseModel

# Request DTOs
class TranscriptionRequest(BaseModel):
    audio_filename: str
    #model_id: str

# class TranscriptionResponse:
#     pass
