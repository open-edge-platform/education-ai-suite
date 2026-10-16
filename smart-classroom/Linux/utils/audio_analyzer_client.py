"""Thin synchronous client for the audio-analyzer microservice.

Transcription is served out-of-process by the containerized audio-analyzer
(``microservices/audio-analyzer`` vendored as a git submodule). The Smart
Classroom backend no longer loads an in-process ASR model; it uploads the
recorded/uploaded audio file to the service and streams back per-chunk
transcription events.

Endpoints used:
    POST /v1/audio/transcriptions/stream   NDJSON, one event per line
    GET  /health                           liveness probe

Event shape (per line of the NDJSON stream):
    {"event": "transcription.chunk", "chunk_index", "language",
     "start_time", "end_time", "text", "segments": [...], "is_final": false}
    {"event": "transcription.completed", "language", "duration", "text",
     "segments": [...], "is_final": true}
where each segment carries ``start``/``end``/``text`` and, when the service
runs diarization, a ``speaker`` label plus an ``is_primary`` verdict.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Iterator, Optional

import requests

from utils.config_loader import config

logger = logging.getLogger(__name__)

# Bypass any system/corporate proxy: the service is reached over the internal
# container network (or localhost in dev); a proxy would 403 those hops.
_NO_PROXY = {"http": None, "https": None}


def _resolve_base_url() -> str:
    """Resolve the audio-analyzer base URL.

    Precedence: ``AUDIO_ANALYZER_URL`` env (set by docker-compose) →
    ``config.audio_analyzer`` host/port → localhost default.
    """
    env_url = os.environ.get("AUDIO_ANALYZER_URL")
    if env_url:
        return env_url.rstrip("/")

    aa = getattr(config, "audio_analyzer", None)
    host = str(getattr(aa, "host_addr", "127.0.0.1")) if aa is not None else "127.0.0.1"
    port = int(getattr(aa, "port", 8010)) if aa is not None else 8010
    return f"http://{host}:{port}"


class AudioAnalyzerClient:
    """Client for the audio-analyzer transcription microservice."""

    def __init__(self) -> None:
        self.base_url = _resolve_base_url()
        self.stream_url = f"{self.base_url}/v1/audio/transcriptions/stream"
        self.health_url = f"{self.base_url}/health"
        aa = getattr(config, "audio_analyzer", None)
        self.request_timeout = float(getattr(aa, "request_timeout_sec", 600)) if aa is not None else 600.0

    def health(self) -> bool:
        """Return True when the service answers its liveness probe."""
        try:
            resp = requests.get(self.health_url, timeout=5.0, proxies=_NO_PROXY)
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001 - health check is best-effort
            logger.warning("audio-analyzer health check failed (%s): %s", self.health_url, exc)
            return False

    def stream_transcribe(
        self,
        audio_path: str,
        *,
        session_id: Optional[str] = None,
        language: Optional[str] = None,
        temperature: float = 0.0,
    ) -> Iterator[dict]:
        """Upload ``audio_path`` and yield decoded NDJSON transcription events.

        Raises ``FileNotFoundError`` if the audio file is missing and
        ``requests.RequestException`` if the service is unreachable, so callers
        can surface a clean error to the API layer.
        """
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        data = {"temperature": str(temperature)}
        if session_id:
            data["session_id"] = session_id
        if language:
            data["language"] = language

        filename = os.path.basename(audio_path)
        with open(audio_path, "rb") as fh:
            files = {"file": (filename, fh, "application/octet-stream")}
            with requests.post(
                self.stream_url,
                files=files,
                data=data,
                stream=True,
                timeout=self.request_timeout,
                proxies=_NO_PROXY,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except ValueError:
                        logger.warning("audio-analyzer sent a non-JSON line: %r", line[:200])
