# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""A converted model counts as ready only with its weights.

A download writes each small ``.xml`` long before its ``.bin``. Closing the app
during the first start used to leave a model that passed the readiness check
and then failed to load ("Empty weights data in bin file"), instead of
resuming its download.
"""

import os
import sys
from pathlib import Path

_SC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONTENT_SEARCH = os.path.join(_SC_ROOT, "content_search")
if _CONTENT_SEARCH not in sys.path:
    sys.path.append(_CONTENT_SEARCH)

from providers.utils.model_utils import is_model_ready


def _ir(directory: Path, stem: str, weights: bytes = b"\0" * 8) -> None:
    (directory / f"{stem}.xml").write_text("<net/>", encoding="utf-8")
    if weights is not None:
        (directory / f"{stem}.bin").write_bytes(weights)


def _vlm(directory: Path) -> Path:
    directory.mkdir(parents=True)
    for stem in ("openvino_language_model", "openvino_vision_embeddings_model",
                 "openvino_tokenizer", "openvino_detokenizer"):
        _ir(directory, stem)
    return directory


def test_a_complete_model_is_ready(tmp_path):
    assert is_model_ready(_vlm(tmp_path / "m"), require_detokenizer=True)


def test_an_interrupted_download_is_not_ready(tmp_path):
    model = _vlm(tmp_path / "m")
    (model / "openvino_vision_embeddings_model.bin").unlink()
    assert not is_model_ready(model, require_detokenizer=True)


def test_empty_model_weights_are_not_ready(tmp_path):
    model = _vlm(tmp_path / "m")
    (model / "openvino_language_model.bin").write_bytes(b"")
    assert not is_model_ready(model, require_detokenizer=True)


def test_tokenizer_weights_must_exist_but_may_be_empty(tmp_path):
    model = _vlm(tmp_path / "m")
    (model / "openvino_detokenizer.bin").write_bytes(b"")
    assert is_model_ready(model, require_detokenizer=True)
    (model / "openvino_detokenizer.bin").unlink()
    assert not is_model_ready(model, require_detokenizer=True)
    # An encoder model needs no detokenizer at all.
    assert is_model_ready(model)


def test_missing_irs_are_not_ready(tmp_path):
    model = tmp_path / "m"
    assert not is_model_ready(model)
    model.mkdir()
    _ir(model, "openvino_tokenizer")
    assert not is_model_ready(model)
    _ir(model, "openvino_model")
    assert is_model_ready(model)
