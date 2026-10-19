# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Standalone model-conversion entry point.

Run as a script (``python convert_worker.py ...``) by
:func:`utils.utils.convert_model` so that all memory used during quantization and
export is reclaimed by the OS when the process exits. ``python convert_worker.py
optimum-cli <args>`` runs the optimum CLI the same way (used by
``utils.ensure_model``).

This module is deliberately self-contained: it imports nothing from the
smart-classroom application packages. Using ``multiprocessing.Process`` here
would make Windows' spawn start method re-execute the parent's ``__main__``
(``main.py``) in the child, which both re-runs the whole application import
graph and is sensitive to top-level package-name collisions on ``sys.path``.
"""

import argparse
import importlib
import logging
import sys

logger = logging.getLogger("convert_worker")

# Optional to optimum-intel (only calibration-based quantization uses it), but
# imported eagerly whenever it is installed. ``datasets`` imports pyarrow, whose
# DLLs Windows Application Control (Smart App Control, WDAC) may refuse to load,
# which would fail every export although none of them needs it.
OPTIONAL_MODULES = ("datasets",)


def skip_unloadable_optional_modules() -> None:
    """Treat an optional module that cannot be loaded as not installed.

    A failed probe leaves ``sys.modules[name] = None``: ``import`` then raises
    ImportError and ``importlib.util.find_spec`` returns None, which is how
    optimum-intel and transformers detect a missing optional package. The
    blocked file itself is never loaded.
    """
    for name in OPTIONAL_MODULES:
        try:
            importlib.import_module(name)
        except ImportError as exc:
            sys.modules[name] = None
            logger.warning("Optional module %s cannot be loaded (%s); exporting without it.",
                           name, exc)


def convert(model_id: str, cache_dir: str, model_type: str, weight_format: str) -> None:
    skip_unloadable_optional_modules()
    import openvino as ov
    from openvino_tokenizers import convert_tokenizer
    from optimum.exporters.openvino.utils import save_preprocessors
    from optimum.intel import (
        OVModelForCausalLM,
        OVModelForFeatureExtraction,
        OVModelForSequenceClassification,
        OVModelForVisualCausalLM,
    )
    from optimum.utils.save_utils import maybe_load_preprocessors
    from transformers import AutoTokenizer

    hf_tokenizer = AutoTokenizer.from_pretrained(model_id)
    hf_tokenizer.save_pretrained(cache_dir)
    add_special_tokens = model_type in ("embedding", "reranker")
    needs_detokenizer = model_type in ("llm", "vlm")
    if needs_detokenizer:
        ov_tokenizer, ov_detokenizer = convert_tokenizer(
            hf_tokenizer, add_special_tokens=add_special_tokens, with_detokenizer=True
        )
        ov.save_model(ov_tokenizer, f"{cache_dir}/openvino_tokenizer.xml")
        ov.save_model(ov_detokenizer, f"{cache_dir}/openvino_detokenizer.xml")
    else:
        ov_tokenizer = convert_tokenizer(hf_tokenizer, add_special_tokens=add_special_tokens)
        ov.save_model(ov_tokenizer, f"{cache_dir}/openvino_tokenizer.xml")

    if model_type == "embedding":
        embedding_model = OVModelForFeatureExtraction.from_pretrained(
            model_id, export=True
        )
        embedding_model.save_pretrained(cache_dir)
    elif model_type == "reranker":
        reranker_model = OVModelForSequenceClassification.from_pretrained(
            model_id, export=True
        )
        reranker_model.save_pretrained(cache_dir)
    elif model_type == "llm":
        llm_model = OVModelForCausalLM.from_pretrained(
            model_id, export=True, weight_format=weight_format
        )
        llm_model.save_pretrained(cache_dir)
    elif model_type == "vlm":
        vlm_model = OVModelForVisualCausalLM.from_pretrained(
            model_id, export=True, weight_format=weight_format
        )
        vlm_model.save_pretrained(cache_dir)
        preprocessors = maybe_load_preprocessors(model_id)
        save_preprocessors(preprocessors, vlm_model.config, cache_dir, True)
    else:
        raise ValueError(f"Unsupported model type: {model_type}")


def optimum_cli(argv: list) -> int:
    """``optimum-cli <argv>`` with the same optional-module handling as :func:`convert`."""
    skip_unloadable_optional_modules()
    from optimum.commands.optimum_cli import main as cli_main

    sys.argv = ["optimum-cli", *argv]
    try:
        cli_main()
    except SystemExit as exc:  # argparse and the export commands exit this way
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["optimum-cli"]:
        logging.basicConfig(level=logging.INFO)
        return optimum_cli(argv[1:])
    parser = argparse.ArgumentParser(description="Convert a model to OpenVINO IR.")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--model-type", required=True,
                        choices=("embedding", "reranker", "llm", "vlm"))
    parser.add_argument("--weight-format", required=True)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(process)d] [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        convert(args.model_id, args.cache_dir, args.model_type, args.weight_format)
    except Exception:
        logger.exception("Model conversion failed for %s", args.model_id)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
