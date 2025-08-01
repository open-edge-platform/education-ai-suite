from pydantic import BaseModel

class SummaryRequest(BaseModel):
    audio_filename: str
    #transcribe_model_id: str
    #summarize_model_id: str

# class SummaryResponse:
#     pass
