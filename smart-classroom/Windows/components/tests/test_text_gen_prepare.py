# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Startup preparation: policy, drafter acquisition, DFlash target derivation, manifest.

Hub access, export and the target download are stubbed at their boundaries; the
IR files are tiny synthetic XML so derivation runs for real.
"""

import dataclasses
import json
import os
import time
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


def test_target_download_is_retried_but_a_local_export_is_not(tmp_path, monkeypatch):
    attempts = []

    def convert(name, cache_dir, model_type, weight_format):
        attempts.append(name)
        if len(attempts) == 1:
            raise RuntimeError("connection reset")
        (Path(cache_dir) / "ready").write_text("1", encoding="utf-8")

    def ready(model_dir, require_detokenizer):
        return (Path(model_dir) / "ready").is_file()

    monkeypatch.setattr(prep, "_convert_helpers", lambda: (convert, ready))
    monkeypatch.setattr(prep.time, "sleep", lambda s: None)
    monkeypatch.setattr(prep, "check_tokenizer_runtime", lambda model_dir, installed: None)
    catalog = SimpleNamespace(model_name="Qwen/Qwen3.5-9B", weight_format="int4",
                              target_dir=tmp_path / "int4")
    assert prep._prepare_target(catalog) == catalog.target_dir and len(attempts) == 2
    attempts.clear()
    custom = SimpleNamespace(model_name="org/custom", weight_format="int4",
                             target_dir=tmp_path / "custom")
    with pytest.raises(prep.PreparationError, match="connection reset"):
        prep._prepare_target(custom)
    assert len(attempts) == 1


def test_successful_export_sets_the_previous_drafter_aside(tmp_path, monkeypatch):
    def run(cmd, env=None, check=False):
        staging = Path(cmd[-1])
        staging.mkdir(parents=True)
        for name in prep._DRAFT_IR_FILES:
            (staging / name).write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(prep.subprocess, "run", run)
    settings = resolve_plan(SimpleNamespace(
        vlm_name="Qwen/Qwen3.6-35B-A3B", weight_format="int4", device="GPU",
        speculative={"mode": "auto"})).speculative
    source = _write_draft(tmp_path / "src")
    draft_dir = _write_draft(tmp_path / "int4", prepared=COMMIT)
    prep._export_draft(source, draft_dir, settings, "z-lab/x", OTHER)
    assert json.loads((draft_dir / ".prepared.json").read_text())["revision"] == OTHER
    assert "dflash_config" in json.loads((draft_dir / "config.json").read_text())
    # The superseded drafter is moved aside, not deleted (rollback).
    assert any(p.name.startswith("int4.superseded-") for p in tmp_path.iterdir())


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


def test_file_errors_fall_back_in_auto_and_fail_in_on(env, monkeypatch):
    def locked(*args):
        raise PermissionError("drafter file is in use")

    monkeypatch.setattr(prep, "_download_source", locked)
    result = prep.prepare(_plan(env, mode="auto"), genai_version=GENAI)
    assert result.speculative is None and "in use" in result.speculative_error
    with pytest.raises(PermissionError):
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


def test_derived_target_is_rebuilt_for_a_drafter_reading_other_layers(tmp_path):
    target = _write_target(tmp_path / "int4")
    derived = prep.ensure_dflash_target(target, _write_draft(tmp_path / "d", layer_ids=(1, 2)))
    # Same target IR, another drafter: the old annotation would hand it the wrong layers.
    assert prep.ensure_dflash_target(target, _write_draft(tmp_path / "e", layer_ids=(0, 2))) == derived

    import xml.etree.ElementTree as ET
    node = ET.parse(derived / "openvino_language_model.xml").getroot().find(
        f"rt_info/{prep.DFLASH_TARGET_RT_INFO_KEY}")
    assert set(json.loads(node.get("value"))["layers"]) == {"0", "2"}
    stamp = json.loads((derived / ".derived.json").read_text(encoding="utf-8"))
    assert stamp["target_layer_ids"] == [0, 2]


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


# --- locking ------------------------------------------------------------------------
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


def test_artifact_lock_tells_a_reused_process_id_from_its_owner(tmp_path):
    pytest.importorskip("psutil")
    lock = prep.ArtifactLock(tmp_path / "a")
    parent = os.getppid()  # a live process other than this one
    lock.path.write_text(f"{parent} {prep._process_started(parent)}", encoding="ascii")
    assert not lock._stale()
    lock.path.write_text(f"{parent} 12345", encoding="ascii")  # same id, another process
    assert lock._stale()
    lock.path.write_text("", encoding="ascii")  # owner died before writing its id
    assert not lock._stale()
    old = time.time() - prep._EMPTY_LOCK_GRACE_S - 5
    os.utime(lock.path, (old, old))
    assert lock._stale()


# --- drafter with its own lm_head -------------------------------------------------
def _write_head_pair(tmp_path, asymmetric: bool):
    """A tiny target whose lm_head uses optimum-intel's int8 chain, and a drafter
    that ends at last_hidden_state; returns (target_dir, draft_dir, dequantized head)."""
    np = pytest.importorskip("numpy")
    ov = pytest.importorskip("openvino")
    import openvino.opset13 as ops

    vocab, hidden = 64, 256
    rng = np.random.default_rng(0)
    scale = (rng.random((vocab, 1)) * 0.02 + 0.01).astype(np.float16)
    x = ops.parameter([1, 2, hidden], ov.Type.f32)
    if asymmetric:
        weight = rng.integers(0, 256, (vocab, hidden), dtype=np.uint8)
        zero_point = rng.integers(100, 156, (vocab, 1), dtype=np.uint8)
        decompressed = ops.subtract(ops.convert(ops.constant(weight), ov.Type.f16),
                                    ops.convert(ops.constant(zero_point), ov.Type.f16))
        dense = (weight.astype(np.float32) - zero_point) * scale.astype(np.float32)
    else:
        weight = rng.integers(-127, 128, (vocab, hidden), dtype=np.int8)
        decompressed = ops.convert(ops.constant(weight), ov.Type.f16)
        dense = weight.astype(np.float32) * scale.astype(np.float32)
    head = ops.convert(ops.multiply(decompressed, ops.constant(scale)), ov.Type.f32)
    matmul = ops.matmul(x, head, False, True)
    matmul.set_friendly_name("__module.model.lm_head/ov_ext::linear/MatMul")
    target = tmp_path / "target"
    ov.save_model(ov.Model([ops.result(matmul)], [x]), str(target / "openvino_language_model.xml"),
                  compress_to_fp16=False)

    h = ops.parameter([1, -1, hidden], ov.Type.f32)
    last = ops.result(ops.multiply(h, ops.constant(np.float32(2.0))))
    last.output(0).get_tensor().set_names({"last_hidden_state"})
    draft = tmp_path / "draft" / "int4"
    ov.save_model(ov.Model([last], [h]), str(draft / "openvino_model.xml"))
    (draft / "config.json").write_text("{}", encoding="utf-8")
    return target, draft, dense


@pytest.mark.parametrize("asymmetric", [False, True])
def test_draft_head_reproduces_the_target_head_in_int4(tmp_path, asymmetric):
    np = pytest.importorskip("numpy")
    ov = pytest.importorskip("openvino")
    target, draft, dense = _write_head_pair(tmp_path, asymmetric)
    derived = prep.ensure_draft_head(target, draft)
    assert derived == draft.with_name("int4-lmhead")
    assert (derived / "config.json").is_file() and (derived / ".derived.json").is_file()
    model = ov.Core().read_model(str(derived / "openvino_model.xml"))
    assert [o.get_names() for o in model.outputs] == [{"logits"}]
    probe = np.random.default_rng(1).standard_normal((1, 3, dense.shape[1])).astype(np.float32)
    exact = {"INFERENCE_PRECISION_HINT": "f32", "DYNAMIC_QUANTIZATION_GROUP_SIZE": "0"}
    got = ov.Core().compile_model(model, "CPU", exact)(probe)[0]
    # Exactly the int4 codes and scales written (low nibble first)...
    packed, scales = prep._requantize_int4(
        *prep._target_lm_head(target / "openvino_language_model.xml"))
    nibbles = np.stack([packed & 0x0F, packed >> 4], axis=-1).reshape(*packed.shape[:2], -1)
    codes = np.where(nibbles > 7, nibbles.astype(np.int16) - 16, nibbles).astype(np.float32)
    int4 = (codes * scales.astype(np.float32)).reshape(dense.shape)
    expected = (2.0 * probe) @ int4.T
    assert np.abs(got - expected).max() / np.abs(expected).max() < 1e-3
    # ...which stay within int4 rounding of the int8 head.
    assert np.abs(int4 - dense).max() <= np.abs(dense).max() / 7
    # Reused while target and drafter are unchanged; a drafter with logits is kept as-is.
    stamp = (derived / ".derived.json").stat().st_mtime_ns
    assert prep.ensure_draft_head(target, draft) == derived
    assert (derived / ".derived.json").stat().st_mtime_ns == stamp
    assert prep.ensure_draft_head(target, derived) == derived


def test_draft_head_failure_keeps_the_stock_drafter(tmp_path):
    pytest.importorskip("openvino")
    target, draft, _ = _write_head_pair(tmp_path, asymmetric=False)
    xml = target / "openvino_language_model.xml"
    xml.write_text(xml.read_text(encoding="utf-8").replace("lm_head", "other"), encoding="utf-8")
    assert prep.ensure_draft_head(target, draft) == draft
    assert not draft.with_name("int4-lmhead").exists()
