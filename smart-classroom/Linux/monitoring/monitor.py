import logging
import os

import httpx

logger = logging.getLogger(__name__)

METRICS_COLLECTOR_URL = os.environ.get(
    "METRICS_COLLECTOR_URL", "http://metrics-collector:9000"
).rstrip("/")
_TIMEOUT_SECONDS = float(os.environ.get("METRICS_COLLECTOR_TIMEOUT", "3"))

_EMPTY_METRICS = {
    "cpu_utilization": [],
    "gpu_utilization": [],
    "npu_utilization": [],
    "memory": [],
    "power": [],
}

def is_monitoring_active() -> bool:
    """Best-effort liveness check against the sidecar's /health endpoint."""
    try:
        resp = httpx.get(f"{METRICS_COLLECTOR_URL}/health", timeout=_TIMEOUT_SECONDS, trust_env=False)
        return resp.status_code == 200
    except httpx.HTTPError as e:
        logger.debug("metrics-collector health check failed: %s", e)
        return False


def get_metrics() -> dict:
    """Fetch the current time-series window from the metrics-collector sidecar.

    The sidecar collects continuously and is not session-scoped; the caller
    is only expected to poll this while a session is active.
    """
    try:
        # trust_env=False: container-internal hop, a corporate HTTP(S)_PROXY
        # env var would otherwise route it off-host and come back as a 504.
        resp = httpx.get(f"{METRICS_COLLECTOR_URL}/metrics", timeout=_TIMEOUT_SECONDS, trust_env=False)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning(
            "metrics-collector unreachable at %s: %s", METRICS_COLLECTOR_URL, e
        )
        return dict(_EMPTY_METRICS)


def get_platform_info() -> dict:
    """Fetch the hardware summary (Processor/iGPU/NPU/Memory/Storage) from the
    metrics-collector sidecar. Returns {} if the sidecar is unreachable, so
    callers can fall back to local detection (see utils/platform_info.py).
    """
    try:
        resp = httpx.get(f"{METRICS_COLLECTOR_URL}/platform-info", timeout=_TIMEOUT_SECONDS, trust_env=False)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.warning(
            "metrics-collector platform-info unreachable at %s: %s",
            METRICS_COLLECTOR_URL, e,
        )
        return {}
