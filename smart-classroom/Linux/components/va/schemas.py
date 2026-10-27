"""Request DTOs for the Video Analytics HTTP API.
"""
from typing import Optional

from pydantic import BaseModel


class VideoAnalyticsRequest(BaseModel):
    """One pipeline launch request item.

    pipeline_name: one of ``front`` / ``back`` / ``content``.
    source: local file path or ``rtsp://`` URL for that camera feed.
    output_stream: when False the annotated video is discarded (no stream URL).
    """

    pipeline_name: str
    source: Optional[str] = None
    output_stream: bool = True


class VideoAnalyticsStopRequest(BaseModel):
    """One pipeline stop request item."""

    pipeline_name: str
