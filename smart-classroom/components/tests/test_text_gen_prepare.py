# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Startup preparation: policy, drafter acquisition, DFlash target derivation, manifest.

Hub access, export and the target download are stubbed at their boundaries; the
IR files are tiny synthetic XML so derivation runs for real.
"""

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from components.vlm import text_gen_prepare as prep
from components.vlm import text_gen_profiles
from components.vlm.text_gen_profiles import SpeculativeUnavailableError, resolve_plan

# The catalog's pinned drafter commit.
COMMIT = text_gen_profiles.target_profile("Qwen/Qwen3.6-35B-A3B").methods["dflash"].draft_revision
OTHER = "fedcba9876543210fedcba9876543210fedcba98"


def _ir_xml(layers=3, rt_info=None) -> str:
    body = "".join(
        f'<layer id="{i}" name="__module.model.language_model.layers.{i}/aten::add/Add_1" '
        f'type="Add" version="opset1"><output><port id="2" precision="FP32">'
        f"<dim>-1</dim><dim>-1</dim><dim>16</dim></port></output></layer>"
        for i in range(layers)
    )
    extra = f'<{rt_info} value="x" />' if rt_info else ""
    return (f'<?xml version="1.0"?><net name="m" version="11"><layers>{body}</layers>'
            f'<edges /><rt_info><other value="1" />{extra}</rt_info></net>')


def _write_target(path: Path, rt_info=None, vocab=100) -> Path:
    path.mkdir(parents=True)
    (path / "openvino_language_model.xml").write_text(_ir_xml(rt_info=rt_info), encoding="utf-8")
    (path / "openvino_language_model.bin").write_bytes(b"\0" * 64)
    (path / "openvino_tokenizer.xml").write_text("<net/>", encoding="utf-8")
    (path / "config.json").write_text(json.dumps(
        {"text_config": {"num_hidden_layers": 3, "vocab_size": vocab}}), encoding="utf-8")
    return path


def _write_draft(path: Path, layer_ids=(1, 2), block_size=16, vocab=100, prepared=None) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "openvino_model.xml").write_text("<net/>", encoding="utf-8")
    (path / "openvino_model.bin").write_bytes(b"\0")
    (path / "config.json").write_text(json.dumps({
        "vocab_size": vocab,
        "dflash_config": {"target_layer_ids": list(layer_ids), "block_size": block_size},
    }), encoding="utf-8")
    if prepared:
        (path / ".prepared.json").write_text(json.dumps({"revision": prepared}), encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models" / "openvino"
    monkeypatch.setattr(text_gen_profiles, "OPENVINO_MODELS_DIR", models)
    monkeypatch.setattr(prep, "MANIFEST_DIR", models / ".manifests")
    monkeypatch.setattr(prep, "HF_SOURCES_DIR", tmp_path / "models" / "hf")
    monkeypatch.setattr(prep, "_prepare_target", lambda plan: plan.target_dir)
    monkeypatch.setattr(prep, "_repo_size", lambda repo, rev: 0)
    hub = SimpleNamespace(resolved=[], downloads=[], exports=[])

    def resolve(repo):
        hub.resolved.append(repo)
        return COMMIT

    def snapshot(repo, local_dir, revision, allow_patterns=None):
        hub.downloads.append((repo, revision, allow_patterns))
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "config.json").write_text(json.dumps({
            "vocab_size": 100,
            "dflash_config": {"target_layer_ids": [1, 2], "block_size": 16}}), encoding="utf-8")

    def export(source_dir, draft_dir, settings, repo, revision):
        hub.exports.append((repo, revision))
        _write_draft(draft_dir, prepared=revision)

    monkeypatch.setattr(prep, "_resolve_revision", resolve)
    monkeypatch.setattr(prep, "_snapshot", snapshot)
    monkeypatch.setattr(prep, "_export_draft", export)
    hub.models = models
    return hub


def _plan(env, name="Qwen/Qwen3.6-35B-A3B", weight="int4", rt_info=None, **speculative):
    node = SimpleNamespace(vlm_name=name, weight_format=weight, device="GPU",
                           speculative=speculative or None)
    plan = resolve_plan(node)
    target = env.models / name.split("/")[-1] / weight
    if not target.exists():
        _write_target(target, rt_info=rt_info)
    return dataclasses.replace(plan, target_dir=target)


GENAI = lambda: "2026.4.1.0"  # noqa: E731


# --- plain and fallback policy ---------------------------------------------------
def test_plain_plan_prepares_only_the_target(env):
    result = prep.prepare(_plan(env), genai_version=GENAI)
    assert result.speculative is None and result.speculative_error is None
    assert env.downloads == [] and env.exports == []
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["speculative"]["status"] == "off"
    assert manifest["target"]["revision"] is None  # legacy provenance is not claimed


def test_auto_dflash_downloads_pinned_source_exports_and_derives_target(env):
    plan = _plan(env, mode="auto")
    result = prep.prepare(plan, genai_version=GENAI)
    spec = result.speculative
    assert spec is not None and spec.draft_revision == COMMIT
    # Configuration and weights only: repository code is never fetched.
    assert env.downloads == [("z-lab/Qwen3.6-35B-A3B-DFlash", COMMIT, ["*.json", "*.safetensors"])]
    # Stock export lacks the hidden-state metadata: a derived sibling is used,
    # the ordinary target stays untouched for plain generation.
    assert spec.target_dir.name == "int4-dflash"
    assert not prep.has_model_rt_info(plan.target_dir / "openvino_language_model.xml",
                                      prep.DFLASH_TARGET_RT_INFO_KEY)
    assert prep.has_model_rt_info(spec.target_dir / "openvino_language_model.xml",
                                  prep.DFLASH_TARGET_RT_INFO_KEY)
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["speculative"]["draft_revision"] == COMMIT
    assert manifest["speculative"]["status"] == "ready"


def test_pinned_revision_needs_no_hub_lookup(env):
    prep.prepare(_plan(env, mode="auto"), genai_version=GENAI)
    assert env.resolved == []


def test_unpinned_revision_is_resolved_once_then_reused_from_the_manifest(env):
    plan = _plan(env, mode="auto")
    plan = dataclasses.replace(
        plan, speculative=dataclasses.replace(plan.speculative, draft_revision=None))
    prep.prepare(plan, genai_version=GENAI)
    assert env.resolved == ["z-lab/Qwen3.6-35B-A3B-DFlash"]
    env.resolved.clear()
    second = prep.prepare(plan, genai_version=GENAI)
    assert env.resolved == [] and second.speculative.draft_revision == COMMIT
    assert len(env.exports) == 1  # validated drafter reused


def test_pinned_revision_mismatch_replaces_drafter_when_downloads_allowed(env):
    plan = _plan(env, mode="auto", draft_revision=OTHER)
    _write_draft(plan.speculative.draft_dir(), prepared=COMMIT)
    result = prep.prepare(plan, genai_version=GENAI)
    assert result.speculative.draft_revision == OTHER
    assert env.exports == [("z-lab/Qwen3.6-35B-A3B-DFlash", OTHER)]
    # The superseded drafter is moved aside, not deleted (rollback).
    assert any(p.name.startswith("int4.superseded-") for p in plan.speculative.draft_dir().parent.iterdir())


def test_drafter_export_command_runs_no_repository_code(tmp_path, monkeypatch):
    seen = {}

    def run(cmd, env=None, check=False):
        seen.update(cmd=cmd, env=env)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(prep.subprocess, "run", run)
    settings = resolve_plan(SimpleNamespace(
        vlm_name="Qwen/Qwen3.6-35B-A3B", weight_format="int4", device="GPU",
        speculative={"mode": "auto"})).speculative
    with pytest.raises(prep.PreparationError, match="optimum-intel"):
        prep._export_draft(tmp_path / "src", tmp_path / "int4", settings, "z-lab/x", COMMIT)
    cmd = seen["cmd"]
    assert cmd[cmd.index("-c") + 1] == prep._DFLASH_EXPORT
    assert cmd[cmd.index("--task") + 1] == "text-generation-with-past"
    assert "--trust-remote-code" not in cmd and seen["env"]["HF_HUB_OFFLINE"] == "1"


def test_export_failure_falls_back_in_auto_and_fails_in_on(env, monkeypatch):
    def failing(*args):
        raise prep.PreparationError("drafter export failed")

    monkeypatch.setattr(prep, "_export_draft", failing)
    result = prep.prepare(_plan(env, mode="auto"), genai_version=GENAI)
    assert result.speculative is None and "export failed" in result.speculative_error
    with pytest.raises(prep.PreparationError):
        prep.prepare(_plan(env, mode="on"), genai_version=GENAI)


def test_old_runtime_means_plain_in_auto(env):
    result = prep.prepare(_plan(env, mode="auto"), genai_version=lambda: "2025.4.0")
    assert result.speculative is None and "openvino-genai >= 2026.3" in result.speculative_error
    with pytest.raises(SpeculativeUnavailableError):
        prep.prepare(_plan(env, mode="on"), genai_version=lambda: "2025.4.0")


def test_mismatched_drafter_fails_even_in_auto(env):
    plan = _plan(env, mode="auto")
    _write_draft(plan.speculative.draft_dir(), vocab=999, prepared=COMMIT)
    with pytest.raises(prep.CompatibilityError, match="vocabulary"):
        prep.prepare(plan, genai_version=GENAI)


def test_unqualified_plan_records_reason_without_work(env):
    result = prep.prepare(_plan(env, "Qwen/Qwen3.8-27B", "int4", mode="auto"), genai_version=GENAI)
    assert result.speculative is None and "no catalog-declared" in result.speculative_error
    assert env.downloads == []


# --- local sources --------------------------------------------------------------
def test_local_drafter_is_validated_never_downloaded(env, tmp_path):
    missing = _plan(env, mode="on", draft_source="local", draft_model=str(tmp_path / "nope"))
    with pytest.raises(prep.PreparationError, match="never downloaded"):
        prep.prepare(missing, genai_version=GENAI)
    local = _write_draft(tmp_path / "my-draft")
    plan = _plan(env, mode="on", draft_source="local", draft_model=str(local))
    result = prep.prepare(plan, genai_version=GENAI)
    assert result.speculative.draft_dir == local and env.downloads == []


# --- DFlash compatibility and derivation ----------------------------------------
def test_validate_dflash_pair_rules(tmp_path):
    target = _write_target(tmp_path / "t")
    assert prep.validate_dflash_pair(target, _write_draft(tmp_path / "ok"), 15) == [1, 2]
    with pytest.raises(prep.CompatibilityError, match="block_size"):
        prep.validate_dflash_pair(target, _write_draft(tmp_path / "k"), 16)
    with pytest.raises(prep.CompatibilityError, match="3 layers"):
        prep.validate_dflash_pair(target, _write_draft(tmp_path / "deep", layer_ids=(7,)), 3)
    with pytest.raises(prep.CompatibilityError, match="unique"):
        prep.validate_dflash_pair(target, _write_draft(tmp_path / "dup", layer_ids=(1, 1)), 3)


def test_current_export_with_metadata_is_used_as_is(tmp_path):
    target = _write_target(tmp_path / "t", rt_info=prep.DFLASH_TARGET_RT_INFO_KEY)
    assert prep.ensure_dflash_target(target, _write_draft(tmp_path / "d")) == target
    assert not (tmp_path / "t-dflash").exists()


def test_derived_target_links_weights_and_annotates_layers(tmp_path):
    target = _write_target(tmp_path / "int4")
    before = (target / "openvino_language_model.xml").read_bytes()
    derived = prep.ensure_dflash_target(target, _write_draft(tmp_path / "d"))
    assert derived == tmp_path / "int4-dflash"
    assert (target / "openvino_language_model.xml").read_bytes() == before
    assert (derived / "openvino_language_model.bin").read_bytes() == b"\0" * 64

    import xml.etree.ElementTree as ET
    node = ET.parse(derived / "openvino_language_model.xml").getroot().find(
        f"rt_info/{prep.DFLASH_TARGET_RT_INFO_KEY}")
    layers = json.loads(node.get("value"))["layers"]
    assert set(layers) == {"1", "2"}
    assert layers["1"]["producer"].endswith("layers.1/aten::add/Add_1")
    stamp = json.loads((derived / ".derived.json").read_text(encoding="utf-8"))
    assert stamp["source_xml_sha256"] == prep.sha256_file(target / "openvino_language_model.xml")
    # Reused while the source is unchanged.
    assert prep.ensure_dflash_target(target, _write_draft(tmp_path / "d")) == derived


def test_has_model_rt_info_ignores_per_layer_rt_info(tmp_path):
    xml = tmp_path / "m.xml"
    xml.write_text('<net><layers><layer id="0"><rt_info><hidden_states_decoder_layers '
                   'value="x"/></rt_info></layer></layers><rt_info/></net>', encoding="utf-8")
    assert not prep.has_model_rt_info(xml, prep.DFLASH_TARGET_RT_INFO_KEY)


def test_tokenizer_exported_by_newer_runtime_is_refused(tmp_path):
    (tmp_path / "openvino_tokenizer.xml").write_text(
        '<net><rt_info><openvino_tokenizers_version value="2026.4.0.0-736-a04accf6282" />'
        "</rt_info></net>", encoding="utf-8")
    with pytest.raises(prep.PreparationError, match="2026.4, newer than the installed 2026.3.0.0"):
        prep.check_tokenizer_runtime(tmp_path, "2026.3.0.0")
    prep.check_tokenizer_runtime(tmp_path, "2026.4.1.0")   # patch releases are compatible
    prep.check_tokenizer_runtime(tmp_path, None)           # unknown runtime: not blocked
    prep.check_tokenizer_runtime(tmp_path / "missing", "2026.3.0.0")


# --- locking and CLI --------------------------------------------------------------
def test_artifact_lock_excludes_and_recovers_stale(tmp_path):
    artifact = tmp_path / "a"
    with prep.ArtifactLock(artifact):
        with pytest.raises(prep.PreparationError, match="timed out"):
            with prep.ArtifactLock(artifact, timeout_s=0):
                pass
    stale = tmp_path / "a.lock"
    stale.write_text("999999", encoding="ascii")  # no such process
    with prep.ArtifactLock(artifact, timeout_s=0):
        pass
    assert not stale.exists()
