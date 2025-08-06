from components.asr.base_asr import BaseASR

class Paraformer(BaseASR):
   def __init__(self, model_name=..., device="cpu", revision=...):
       # Load Paraformer model
       pass

   def transcribe(self, audio_path: str) -> str:
       # Return transcribed text from .wav file
       pass