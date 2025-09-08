from utils.logger_config import setup_logger
setup_logger()

from fastapi import FastAPI
from api.endpoints import register_routes
from utils.runtime_config_loader import RuntimeConfig
from utils.ensure_model import ensure_model
from utils.preload_models import preload_models
import logging
from fastapi.middleware.cors import CORSMiddleware
import os
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from pathlib import Path

logger = logging.getLogger(__name__)

app = FastAPI()
origins_env = os.getenv("FRONTEND_ORIGINS", "").strip()
if origins_env:
    allowed_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    allow_creds = True
else:
    # Dev fallback: allow all without credentials (wildcard cannot be used with credentials)
    allowed_origins = ["*"]
    allow_creds = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-session-id"],
)
register_routes(app)
RuntimeConfig.ensure_config_exists()
ensure_model()
preload_models()
# Serve built frontend at root (/) if present
ui_dist = Path(__file__).parent / "ui" / "dist"
if ui_dist.exists():
    app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="static")

    # SPA fallback: return index.html for unknown non-API paths
    @app.get("/{path_name:path}")
    async def spa_fallback(path_name: str):
      return FileResponse(ui_dist / "index.html")
if __name__ == "__main__":
    import uvicorn
    logger.info("App started, Starting Server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
