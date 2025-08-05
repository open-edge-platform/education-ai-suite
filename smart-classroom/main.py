from fastapi import FastAPI
from api.endpoints import register_routes
from components.ffmpeg.audio_preprocessing import chunk_audio_by_silence

app = FastAPI()
register_routes(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
