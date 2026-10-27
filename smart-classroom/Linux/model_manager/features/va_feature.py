import logging
from typing import Dict, List

from fastapi import APIRouter

from api.va import va_router

logger = logging.getLogger(__name__)


class VideoAnalyticsFeature:
    """Video Analytics feature: mounts the VA router (api/va.py).

    Inference runs in the ``video-analytics`` side-car, so ``requires`` is empty
    and ``build`` only logs. Enabling it activates the ``va`` compose profile
    (see ``utils/compose_profiles.py``), bringing up the side-car + mediamtx.
    """

    id: str = "video_analytics"
    requires: List[str] = []
    depends_on: List[str] = []
    router: APIRouter = va_router

    def build(self) -> None:
        logger.info(
            "VideoAnalyticsFeature built — pipelines run in the video-analytics side-car."
        )

    def teardown(self) -> None:
        # The side-car owns pipeline lifecycle; nothing to force-stop here.
        logger.info("VideoAnalyticsFeature torn down.")

    def ui_descriptor(self) -> Dict:
        return {
            "id": self.id,
            "endpoints": {
                "upload": "/upload-video",
                "start": "/start-video-analytics-pipeline",
                "stop": "/stop-video-analytics-pipeline",
                "monitor": "/monitor-video-analytics-pipeline",
                "class_statistics": "/class-statistics",
            },
        }
