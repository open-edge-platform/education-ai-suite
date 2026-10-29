"""Shared GStreamer environment setup. Safe to call from any entry point that is
about to spawn a GStreamer process.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Timeout for short-lived GStreamer helper processes (gst-inspect,
# gst-discoverer). Sized for a full plugin registry rebuild on a cold file
# cache, which is the worst case these calls have to survive.
GST_SUBPROCESS_TIMEOUT = 60

# App-owned location for the plugin registry cache
GST_REGISTRY_RELPATH = Path("storage") / "gstreamer" / "registry.bin"


def ensure_gst_registry() -> None:
    """Point GST_REGISTRY at an app-owned path. Safe to call repeatedly.

    A GST_REGISTRY already present in the environment is left alone, so the
    location can still be overridden from outside the app.
    """
    if os.environ.get("GST_REGISTRY"):
        return

    registry = GST_REGISTRY_RELPATH.resolve()
    registry.parent.mkdir(parents=True, exist_ok=True)
    os.environ["GST_REGISTRY"] = str(registry)
    logger.info(f"GStreamer plugin registry cache pinned to: {registry}")
