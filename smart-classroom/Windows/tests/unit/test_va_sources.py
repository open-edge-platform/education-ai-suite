# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""utils.va_completion.va_pipeline_sources: session video-source names -> VA pipelines."""

import pytest

from utils.va_completion import va_pipeline_sources


def test_board_is_the_content_pipeline_and_empty_sources_are_dropped():
    assert va_pipeline_sources({"front": "f.mp4", "back": "", "board": "b.mp4"}) == {
        "front": "f.mp4", "content": "b.mp4"}
    assert va_pipeline_sources(None) == {}


@pytest.mark.parametrize("sources, message", [
    ({"side": "s.mp4"}, "unknown video source 'side'"),
    ({"board": "a.mp4", "content": "b.mp4"}, "two video sources for the content pipeline"),
])
def test_names_that_are_no_single_pipeline_are_rejected(sources, message):
    with pytest.raises(ValueError, match=message):
        va_pipeline_sources(sources)
