from fastapi import FastAPI
from api.endpoints import register_routes
from components.ffmpeg.audio_preprocessing import chunk_audio_by_silence
import os, time
import atexit
from pipeline import Pipeline

app = FastAPI()
register_routes(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    # Example usage:
    # for chunk in chunk_audio_by_silence(r"C:\Users\intel\workspace-udit\education-ai-suite\smart-classroom\storage\audios\philosophy_10_russell_128kb.mp3"):
    #     print("Processing chunk:", chunk["chunk_path"])
    #     # Delete after use
    #     time.sleep(1)
    #     if os.path.exists(chunk["chunk_path"]):
    #         os.remove(chunk["chunk_path"])
    #     # trigger transcription here

    # time.sleep(120)

    # pipeline = Pipeline(None)
    # pipeline.run_transcription(r"C:\Users\intel\workspace-udit\education-ai-suite\smart-classroom\storage\audios\philosophy_10_russell_128kb.mp3")


        
 