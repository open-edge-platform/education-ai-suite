# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""``load_images``: data-URL images become NHWC uint8 tensors, pixel for pixel."""

import asyncio
import base64
import io
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openvino")
Image = pytest.importorskip("PIL.Image")

_CONTENT_SEARCH = Path(__file__).resolve().parents[2] / "content_search"


def load_images(urls):
    # Imported on use: the serving utils install a logging formatter at import
    # time, so importing them during collection would affect every later test.
    if str(_CONTENT_SEARCH) not in sys.path:
        sys.path.append(str(_CONTENT_SEARCH))
    from components.vlm.vlm_openvino_serving.utils.utils import load_images as load

    return load(urls)


def _data_url(image, fmt="PNG"):
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "P"])
def test_tensor_matches_the_decoded_pixels(mode):
    rng = np.random.default_rng(0)
    src = Image.fromarray(rng.integers(0, 256, (5, 7, 3), dtype=np.uint8)).convert(mode)
    images, tensors = asyncio.run(load_images([_data_url(src)]))
    data = tensors[0].data
    assert data.shape == (1, 5, 7, 3) and data.dtype == np.uint8
    # The former per-pixel path, kept here as the reference.
    expected = np.array(images[0].getdata()).reshape(1, 5, 7, 3).astype(np.uint8)
    assert np.array_equal(data, expected)


def test_invalid_base64_is_a_value_error():
    with pytest.raises(ValueError):
        asyncio.run(load_images(["data:image/png;base64,abc"]))  # bad padding
