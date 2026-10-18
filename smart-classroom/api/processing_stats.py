# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Workflow-stage and model-call processing-time statistics."""

from typing import Optional

from fastapi import APIRouter, Query

from utils.processing_stats import STATS

router = APIRouter()


@router.get("/processing-stats")
def get_processing_stats(
    session_id: Optional[str] = Query(None, max_length=128,
                                      description="Only this session's records"),
    raw: bool = Query(False, description="Include the bounded raw records"),
):
    """Per-stage and per-model distributions (count, total, mean, min/max, p50, p95).

    Successful samples form the distributions; failed and cancelled attempts are
    counted separately. Unavailable measurements are null, never zero.
    """
    return STATS.snapshot(session_id=session_id, include_raw=raw)
