# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Writable app-state root for a packaged install.

The Electron shell injects ``SMART_CLASSROOM_USERDATA`` for the backend and
every service it spawns. When present, models and the conversion venv live under
that user directory so the read-only backend tree (as installed under
``resources/backend``) is never written. In development the variable is unset
and these helpers return ``None`` so each caller falls back to its existing
source-tree relative path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def user_data_dir() -> Optional[Path]:
    v = os.environ.get("SMART_CLASSROOM_USERDATA")
    return Path(v) if v and v.strip() else None


def models_root() -> Optional[Path]:
    data = user_data_dir()
    return data / "models" if data else None


def prefer_user_data() -> bool:
    return user_data_dir() is not None