from components.asr.base_asr import BaseASR

class Whisper(BaseASR):
   def __init__(self, model_name=..., revision=..., device="cpu"):
       # Load Whisper model
       pass

   def transcribe(self, audio_path: str) -> str:
       # Return transcribed text from .wav file
       pass