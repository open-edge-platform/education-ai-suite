"""Config loader for the VA microservice.
"""
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def _dict_to_namespace(d):
    if isinstance(d, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in d.items()})
    return d


def load_config(path=None):
    # Allow override via environment variable VA_CONFIG_PATH.
    path = path or os.environ.get("VA_CONFIG_PATH") or DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return _dict_to_namespace(data)


config = load_config()
