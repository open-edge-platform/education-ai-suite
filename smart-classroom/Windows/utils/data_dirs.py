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


def models_root():
    data = user_data_dir()
    return data / "models" if data else None