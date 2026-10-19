# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""``models.text_gen.speculative`` resolution against the serving catalog."""

from types import SimpleNamespace

import pytest

from components.vlm.text_gen_profiles import (
    SpeculativeConfigError,
    SpeculativeUnavailableError,
    preconverted_repo,
    resolve_plan,
    version_at_least,
)
from utils.model_paths import OPENVINO_MODELS_DIR, SC_ROOT

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _text_gen(name="Qwen/Qwen3.6-35B-A3B", weight="int4", speculative="__absent__"):
    node = {"provider": "vlm", "vlm_name": name, "device": "GPU", "weight_format": weight,
            "max_new_tokens": 5120}
    if speculative != "__absent__":
        node["speculative"] = speculative
    return SimpleNamespace(**node)


# --- backward compatibility ------------------------------------------------
def test_absent_block_is_plain_and_keeps_the_target_path():
    plan = resolve_plan(_text_gen("Qwen/Qwen3-VL-8B-Instruct"))
    assert plan.mode == "off"
    assert plan.speculative is None and not plan.wants_speculative
    assert plan.target_dir == OPENVINO_MODELS_DIR / "Qwen3-VL-8B-Instruct" / "int4"


def test_unknown_older_model_stays_plain_without_catalog_entry():
    plan = resolve_plan(_text_gen("Qwen/Qwen2.5-VL-7B-Instruct"))
    assert plan.target is None and plan.speculative is None
    assert plan.tool_calls_declared is None


def test_off_ignores_dormant_fields_even_if_invalid():
    plan = resolve_plan(_text_gen(speculative={"mode": "off", "method": "bogus", "x": 1}))
    assert plan.mode == "off" and plan.speculative is None


def test_yaml_boolean_off_is_off():
    assert resolve_plan(_text_gen(speculative={"mode": False})).mode == "off"


def test_null_block_is_plain():
    assert resolve_plan(_text_gen(speculative=None)).mode == "off"


def test_namespace_block_from_config_loader_is_accepted():
    plan = resolve_plan(_text_gen(speculative=SimpleNamespace(mode="auto")))
    assert plan.speculative.method == "dflash"


# --- defaults from the catalog ---------------------------------------------
def test_auto_method_selects_catalog_dflash_for_qwen36():
    plan = resolve_plan(_text_gen(speculative={"mode": "auto"}))
    spec = plan.speculative
    assert spec.method == "dflash"
    assert spec.source == "huggingface"
    assert spec.draft_model == "z-lab/Qwen3.6-35B-A3B-DFlash"
    assert spec.num_assistant_tokens == 3
    assert spec.draft_dir() == OPENVINO_MODELS_DIR / "Qwen3.6-35B-A3B-DFlash" / "int4"
    assert spec.profile.scheduler["enable_prefix_caching"] is False


@pytest.mark.parametrize("method", ["auto", "dflash2", "mtp"])
def test_unsupported_methods_are_plain_in_auto_and_fail_in_on(method):
    plan = resolve_plan(_text_gen("Qwen/Qwen3.8-27B", "int8", {"mode": "auto", "method": method}))
    assert plan.speculative is None and plan.plain_reason
    with pytest.raises(SpeculativeUnavailableError, match="mode: auto"):
        resolve_plan(_text_gen("Qwen/Qwen3.8-27B", "int4", {"mode": "on", "method": method}))


def test_qwen35_has_no_qualified_method():
    plan = resolve_plan(_text_gen("Qwen/Qwen3.5-9B", "int4", {"mode": "auto", "method": "dflash"}))
    assert plan.speculative is None and "no qualified dflash" in plan.plain_reason
    with pytest.raises(SpeculativeUnavailableError):
        resolve_plan(_text_gen("Qwen/Qwen3.5-9B", "int4", {"mode": "on"}))


def test_unqualified_precision_falls_back_in_auto():
    plan = resolve_plan(_text_gen("Qwen/Qwen3.6-35B-A3B", "int8", {"mode": "auto"}))
    assert plan.speculative is None and "int8" in plan.plain_reason


def test_explicit_revision_and_tuning_are_kept():
    plan = resolve_plan(_text_gen(speculative={
        "mode": "on", "method": "dflash", "draft_revision": COMMIT, "num_assistant_tokens": 7}))
    assert plan.speculative.draft_revision == COMMIT
    assert plan.speculative.num_assistant_tokens == 7
    assert plan.speculative.describe() == f"z-lab/Qwen3.6-35B-A3B-DFlash@{COMMIT[:12]}"


def test_local_relative_dir_resolves_from_smart_classroom_root():
    plan = resolve_plan(_text_gen(speculative={
        "mode": "auto", "draft_source": "local", "draft_model": "models/my-draft"}))
    assert plan.speculative.draft_dir() == SC_ROOT / "models" / "my-draft"
    assert plan.speculative.describe() == "local IR (my-draft)"


# --- validation failures (never fallback) -----------------------------------
@pytest.mark.parametrize("block, message", [
    ({"mode": "sometimes"}, "speculative.mode"),
    ({"mode": "auto", "method": "eagle"}, "speculative.method"),
    ({"mode": "auto", "draft_source": "s3"}, "speculative.draft_source"),
    ({"mode": "auto", "unknown": 1}, "unknown speculative key"),
    ({"mode": "auto", "num_assistant_tokens": 0}, "positive integer"),
    ({"mode": "auto", "num_assistant_tokens": True}, "positive integer"),
    ({"mode": "auto", "num_assistant_tokens": 16}, "supported range"),
    ({"mode": "auto", "draft_revision": "main"}, "40-character commit"),
    ({"mode": "auto", "draft_model": "z-lab/Qwen3.8-27B-DFlash2"}, "not the qualified"),
    ({"mode": "auto", "draft_source": "local"}, "requires draft_model"),
    ({"mode": "auto", "draft_source": "local", "draft_model": "d", "draft_revision": COMMIT},
     "must be null"),
    ({"mode": "auto", "method": "dflash", "draft_source": "target"}, "only with method: mtp"),
])
def test_invalid_settings_raise(block, message):
    with pytest.raises(SpeculativeConfigError, match=message):
        resolve_plan(_text_gen(speculative=block))


@pytest.mark.parametrize("block, message", [
    ({"mode": "auto", "method": "mtp", "draft_source": "huggingface"}, "bundled prediction head"),
    ({"mode": "auto", "method": "mtp", "draft_model": "z-lab/x"}, "draft_model must be null"),
    ({"mode": "auto", "method": "mtp", "draft_source": "target", "draft_revision": COMMIT},
     "must be null"),
])
def test_invalid_mtp_settings_raise(block, message):
    with pytest.raises(SpeculativeConfigError, match=message):
        resolve_plan(_text_gen("Qwen/Qwen3.8-27B", "int4", block))


def test_catalog_lists_the_new_target_repos():
    assert preconverted_repo("Qwen/Qwen3.8-27B", "int8") == "OpenVINO/Qwen3.8-27B-int8-ov"
    assert preconverted_repo("qwen/qwen3.6-35b-a3b", "INT4") == "OpenVINO/Qwen3.6-35B-A3B-int4-ov"
    assert preconverted_repo("Qwen/Qwen3.6-35B-A3B", "int8") is None


@pytest.mark.parametrize("installed, required, ok", [
    ("2026.3.0.0", "2026.3", True),
    ("2026.5.0.0.dev20260901", "2026.5", True),
    ("2026.3.0.0", "2026.5", False),
    (None, "2026.3", False),
])
def test_version_at_least(installed, required, ok):
    assert version_at_least(installed, required) is ok
