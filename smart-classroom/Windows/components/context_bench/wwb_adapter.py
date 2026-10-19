# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Optional bridge to OpenVINO's who_what_benchmark (WWB) for the embedding-similarity metric.

WWB's similarity is the cosine distance between sentence embeddings of a baseline and a
candidate answer (`sentence-transformers/all-mpnet-base-v2` by default). That metric is
defined by a specific embedding model, so it is delegated rather than reimplemented; every
other fidelity metric (ROUGE, chrF, FDT/SDT) is computed natively in `scoring.py`.

WWB and its embedding model are optional and are acquired during explicit setup, never
during scoring: the evaluator is constructed with Hugging Face offline mode forced, so a
model that is not already cached makes only the similarity column unavailable. A missing
package, a missing model or an unrecognized result shape degrades to "unavailable" with the
reason attached; no other metric is affected and no run fails.

WWB's evaluator return shape has varied between versions (a metrics DataFrame, a
``(mean, per_sample)`` pair, a plain dict) and is not a published API, so `_as_similarities`
normalizes the shapes seen so far and refuses anything else.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"

_MODULE_CANDIDATES = ("whowhatbench.whowhat_metrics", "whowhatbench")

# One loaded embedding model per id: it is hundreds of megabytes and every case in the sweep
# scores against the same one.
_EVALUATOR_CACHE: dict = {}

_OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}


@dataclass(frozen=True)
class SimilarityResult:
    """Per-probe similarities, or the reason there are none.

    `values` is one score per (reference, prediction) pair in input order; `reason` is
    non-None exactly when `values` is None.
    """

    values: list | None
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.values is not None


def unavailable(reason: str) -> SimilarityResult:
    return SimilarityResult(values=None, reason=reason)


@contextlib.contextmanager
def _offline():
    """Force Hugging Face offline mode while the evaluator loads its embedding model.

    huggingface_hub reads HF_HUB_OFFLINE once, at import, so the cached flag is
    switched as well. It is imported first: imported inside the block, it would
    keep offline mode cached after the block ends.
    """
    try:
        import huggingface_hub.constants as constants
    except ImportError:
        constants = None
    previous = {key: os.environ.get(key) for key in _OFFLINE_ENV}
    os.environ.update(_OFFLINE_ENV)
    cached = getattr(constants, "HF_HUB_OFFLINE", None)
    if constants is not None:
        constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        if constants is not None:
            constants.HF_HUB_OFFLINE = cached
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def similarity(references: list, predictions: list,
               model_id: str = DEFAULT_EMBEDDING_MODEL) -> SimilarityResult:
    """WWB's embedding similarity for each (reference, prediction) pair, or why it is missing.

    `references` are the baseline profile's answers and `predictions` the ones being judged,
    the same direction as WWB's `--base-model` / `--target-model` split. WWB reads both as
    DataFrames with an ``answers`` column; pandas is a WWB dependency, imported only here.
    """
    if len(references) != len(predictions):
        raise ValueError(
            f"similarity needs paired inputs; got {len(references)} references "
            f"and {len(predictions)} predictions"
        )
    if not references:
        return unavailable("no probes to score")

    evaluator = _evaluator(model_id)
    if isinstance(evaluator, str):
        return unavailable(evaluator)
    try:
        import pandas as pd

        with _offline():
            raw = evaluator.evaluate(pd.DataFrame({"answers": list(references)}),
                                     pd.DataFrame({"answers": list(predictions)}))
    except Exception as exc:  # noqa: BLE001 - an optional metric must not end the run
        return unavailable(f"who_what_benchmark raised {type(exc).__name__}: {exc}")

    values = _as_similarities(raw, len(references))
    if values is None:
        return unavailable(
            f"could not read a similarity out of {type(raw).__name__} -- "
            "who_what_benchmark's return shape is not one this adapter recognizes"
        )
    return SimilarityResult(values=values)


def _evaluator(model_id: str):
    """A cached `TextSimilarity`, or a string explaining why there is none."""
    if model_id in _EVALUATOR_CACHE:
        return _EVALUATOR_CACHE[model_id]

    import importlib

    text_similarity = None
    for name in _MODULE_CANDIDATES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        text_similarity = getattr(module, "TextSimilarity", None)
        if text_similarity is not None:
            break

    if text_similarity is None:
        result = (
            "who_what_benchmark is not installed (no whowhatbench.TextSimilarity). "
            "Install it during setup to get the embedding-similarity column; every other "
            "accuracy metric is computed natively and is unaffected."
        )
    else:
        try:
            with _offline():
                result = text_similarity(model_id)
        except Exception as exc:  # noqa: BLE001
            result = (
                f"who_what_benchmark could not load the embedding model {model_id!r} "
                f"offline ({type(exc).__name__}); acquire it during setup"
            )
    _EVALUATOR_CACHE[model_id] = result
    return result


def _as_similarities(raw, expected: int) -> list | None:
    """Pull `expected` per-pair similarities out of whatever WWB's evaluator returned.

    A per-sample list of the wrong length is None: aligning it wrongly would put one
    probe's score on another probe's row.
    """
    if isinstance(raw, tuple) and len(raw) == 2:
        for candidate in (raw[1], raw[0]):
            values = _as_similarities(candidate, expected)
            if values is not None:
                return values
        return None

    column = _similarity_column(raw)
    if column is None:
        return None
    try:
        values = [float(v) for v in column]
    except (TypeError, ValueError):
        return None
    if any(value != value or value in (float("inf"), float("-inf")) for value in values):
        return None
    return values if len(values) == expected else None


def _similarity_column(raw):
    """The sequence of similarity numbers inside `raw`, without importing pandas."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return [raw]
    for key in ("similarity", "Similarity"):
        try:
            if key in raw:
                column = raw[key]
                values = getattr(column, "values", column)
                return list(values() if callable(values) else values)
        except TypeError:
            break
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return None
