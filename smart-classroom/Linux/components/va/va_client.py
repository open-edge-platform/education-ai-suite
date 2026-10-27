"""Thin synchronous HTTP client for the video-analytics side-car control API."""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Iterator, List, Optional

import requests

logger = logging.getLogger(__name__)

# Valid pipeline names accepted by the side-car.
VALID_PIPELINE_NAMES = ("front", "back", "content")

# Internal service hop — never route through a proxy.
_NO_PROXY = {"http": None, "https": None}


def resolve_base_url() -> str:
    """Side-car base URL: VIDEO_ANALYTICS_URL env, then config.va_pipeline.endpoint, then localhost."""
    env_url = os.environ.get("VIDEO_ANALYTICS_URL")
    if env_url:
        return env_url.rstrip("/")

    try:
        from utils.config_loader import config

        va = getattr(config, "va_pipeline", None)
        endpoint = getattr(va, "endpoint", None) if va is not None else None
        if endpoint:
            return str(endpoint).rstrip("/")
    except Exception:  # noqa: BLE001 - config is best-effort here
        pass

    return "http://127.0.0.1:8020"


class VideoAnalyticsClient:
    """Client for the video-analytics control API."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or resolve_base_url()).rstrip("/")
        self.health_url = f"{self.base_url}/health"
        self.request_timeout = 30.0

    # ── liveness ──────────────────────────────────────────────────────────
    def health(self) -> bool:
        """Return True when the service answers its liveness probe."""
        try:
            resp = requests.get(self.health_url, timeout=5.0, proxies=_NO_PROXY)
            return resp.status_code == 200
        except Exception as exc:  # noqa: BLE001 - health check is best-effort
            logger.debug("VA health check failed: %s", exc)
            return False

    # ── lifecycle ─────────────────────────────────────────────────────────
    def launch(
        self,
        name: str,
        source: str,
        *,
        device: Optional[str] = None,
        output_dir: str = "outputs",
        output_rtsp: str = "rtsp://mediamtx:8554",
        output_stream: bool = True,
        threshold: float = 0.5,
        record: bool = False,
    ) -> bool:
        """Launch a pipeline. Returns True when the side-car reports it started.

        Raises RuntimeError with the side-car's detail on a 4xx/5xx response.
        """
        payload = {
            "source": source,
            "device": device,
            "output_dir": output_dir,
            "output_rtsp": output_rtsp,
            "output_stream": output_stream,
            "threshold": threshold,
            "record": record,
        }
        resp = requests.post(
            f"{self.base_url}/pipelines/{name}/launch",
            json=payload,
            timeout=self.request_timeout,
            proxies=_NO_PROXY,
        )
        if resp.status_code >= 400:
            raise RuntimeError(self._detail(resp))
        return bool(resp.json().get("launched", False))

    def stop(self, name: str, timeout: float = 10.0) -> bool:
        """Stop a pipeline. Returns True when the side-car reports it stopped."""
        resp = requests.post(
            f"{self.base_url}/pipelines/{name}/stop",
            params={"timeout": timeout},
            timeout=self.request_timeout + timeout,
            proxies=_NO_PROXY,
        )
        if resp.status_code >= 400:
            raise RuntimeError(self._detail(resp))
        return bool(resp.json().get("stopped", False))

    # ── status ────────────────────────────────────────────────────────────
    def get_status(self, name: str) -> Optional[Dict]:
        """Return one pipeline's status, or None when it is not registered."""
        resp = requests.get(
            f"{self.base_url}/pipelines/{name}",
            timeout=self.request_timeout,
            proxies=_NO_PROXY,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(self._detail(resp))
        return resp.json()

    def get_all_status(self) -> Dict[str, Dict]:
        """Return the status dict keyed by currently registered pipeline name."""
        resp = requests.get(
            f"{self.base_url}/pipelines",
            timeout=self.request_timeout,
            proxies=_NO_PROXY,
        )
        if resp.status_code >= 400:
            raise RuntimeError(self._detail(resp))
        return resp.json()

    def stream_status(self, check_interval: float = 2.0) -> Iterator[Dict]:
        """Yield the side-car's /pipelines/status NDJSON objects as they arrive."""
        yield from self._ndjson_stream(
            f"{self.base_url}/pipelines/status",
            params={"check_interval": check_interval},
        )

    def stream_class_statistics(
        self, front_posture_file: str, poll_interval: float = 5.0
    ) -> Iterator[Dict]:
        """Yield the side-car's /class-statistics NDJSON objects as they arrive."""
        yield from self._ndjson_stream(
            f"{self.base_url}/class-statistics",
            params={
                "front_posture_file": front_posture_file,
                "poll_interval": poll_interval,
            },
        )

    def latest_class_statistics(
        self, front_posture_file: str, poll_interval: float = 1.0
    ) -> Optional[Dict]:
        """Read a single cumulative statistics object and close the stream.

        The side-car recomputes statistics over the whole posture file on every
        poll, so the first emitted line already reflects the full file — ideal
        for a one-shot aggregation after all pipelines finish.
        """
        for stats in self.stream_class_statistics(front_posture_file, poll_interval):
            return stats
        return None

    # ── helpers ───────────────────────────────────────────────────────────
    def _ndjson_stream(self, url: str, params: Dict) -> Iterator[Dict]:
        with requests.get(
            url,
            params=params,
            stream=True,
            timeout=(self.request_timeout, None),
            proxies=_NO_PROXY,
        ) as resp:
            if resp.status_code >= 400:
                raise RuntimeError(self._detail(resp))
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("VA stream: skipping non-JSON line: %r", line)

    @staticmethod
    def _detail(resp: requests.Response) -> str:
        try:
            return str(resp.json().get("detail", resp.text))
        except Exception:  # noqa: BLE001
            return resp.text or f"HTTP {resp.status_code}"


# Process-wide default client (lazy base-url resolution happens at construction).
_default_client: Optional[VideoAnalyticsClient] = None


def get_client() -> VideoAnalyticsClient:
    """Return a shared VideoAnalyticsClient instance."""
    global _default_client
    if _default_client is None:
        _default_client = VideoAnalyticsClient()
    return _default_client
