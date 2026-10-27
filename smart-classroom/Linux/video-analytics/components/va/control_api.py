"""VA microservice control API.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from components.va.va_pipeline_service import (
    PipelineName,
    PipelineOptions,
    VideoAnalyticsPipelineService,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="VA Pipeline Control API")

# One service instance per process, same lifecycle as the app itself.
service = VideoAnalyticsPipelineService()

_VALID_PIPELINE_NAMES = {p.value for p in PipelineName}


@app.get("/health")
def health():
    """Liveness/readiness probe used by the docker-compose healthcheck."""
    return {"status": "ok", "service": "video-analytics"}


class LaunchRequest(BaseModel):
    source: str
    device: Optional[str] = None
    output_dir: str = "outputs"
    output_rtsp: str = "rtsp://127.0.0.1:8554"
    output_stream: bool = True
    threshold: float = 0.5
    record: bool = False


def _require_valid_name(name: str) -> None:
    if name not in _VALID_PIPELINE_NAMES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown pipeline '{name}'. Valid names: {sorted(_VALID_PIPELINE_NAMES)}",
        )


@app.post("/pipelines/{name}/launch")
def launch_pipeline(name: str, request: LaunchRequest):
    _require_valid_name(name)
    options = PipelineOptions(
        device=request.device,
        output_dir=request.output_dir,
        output_rtsp=request.output_rtsp,
        output_stream=request.output_stream,
        threshold=request.threshold,
        record=request.record,
    )
    try:
        launched = service.launch_pipeline(name, request.source, options)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"launched": launched}


@app.post("/pipelines/{name}/stop")
def stop_pipeline(name: str, timeout: float = 10.0):
    _require_valid_name(name)
    stopped = service.stop_pipeline(name, timeout)
    return {"stopped": stopped}


# Registered before "/pipelines/{name}" so the literal path wins the match.
@app.get("/pipelines/status")
async def stream_pipeline_status(check_interval: float = 2.0):
    """VA-13: streams monitor_pipeline_status() as newline-delimited JSON."""

    async def event_stream():
        async for status in service.monitor_pipeline_status(check_interval=check_interval):
            yield json.dumps(status) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.get("/pipelines/{name}")
def get_pipeline_status(name: str):
    _require_valid_name(name)
    status = service.get_pipeline_status(name)
    if status is None:
        raise HTTPException(status_code=404, detail=f"Pipeline '{name}' is not registered")
    return status


@app.get("/pipelines")
def get_all_pipelines_status():
    return service.get_all_pipelines_status()


@app.get("/class-statistics")
async def stream_class_statistics(
    front_posture_file: str = "outputs/front_posture.txt",
    poll_interval: float = 5.0,
):
    """VA-13: streams VA-3's get_pose_stats() output as newline-delimited JSON,
    polling front_posture_file every poll_interval seconds.
    """
    posture_path = Path(front_posture_file)

    async def event_stream():
        previous_state: Optional[dict] = None
        while True:
            stats, previous_state = service.get_pose_stats(str(posture_path), previous_state)
            yield json.dumps(stats) + "\n"
            await asyncio.sleep(poll_interval)

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
