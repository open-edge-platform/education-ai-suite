from utils.logger_config import setup_logger
setup_logger()

from fastapi import FastAPI
from api.endpoints import register_routes
from components.ffmpeg.audio_preprocessing import chunk_audio_by_silence
from utils.runtime_config_loader import RuntimeConfig
import logging

logger = logging.getLogger(__name__)

app = FastAPI()
register_routes(app)
RuntimeConfig.ensure_config_exists()


if __name__ == "__main__":
    import uvicorn
    logger.info("App started, Starting Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
