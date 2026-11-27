# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Writable app-state root for a packaged install."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def user_data_dir():
    v = os.environ.get("SMART_CLASSROOM_USERDATA")
    return Path(v) if v and v.strip() else None


def writable_path(configured) -> Path:
    """Where the backend writes something ``config.yaml`` names by a path.

    In an installed app the working folder is the program folder, which the
    app cannot write when it is installed for every user (Program Files), so a
    relative path resolves against the user data folder. An absolute path, or
    any path in a source checkout, is used as it is.
    """
    path = Path(configured)
    data = user_data_dir()
    return data / path if data and not path.is_absolute() else path


def models_root():
    data = user_data_dir()
    return data / "models" if data else None

def models_base_path() -> str:
    root = models_root()
    return str(root) if root else "models"