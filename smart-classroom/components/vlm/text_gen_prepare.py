# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Prepare the ``text_gen`` target and speculative artifacts before serving.

The model owner calls :func:`prepare` when it loads the warm VLM, so every
startup path (``start-smart-classroom.ps1``, the desktop app, ``python main.py``)
prepares the same way: the first start downloads or converts what is missing,
later starts only validate. Request handlers never download or convert.

Order of work (see the serving design, "Model Preparation"):

1. **Select** -- :func:`components.vlm.text_gen_profiles.resolve_plan`.
2. **Prepare** -- the target through the existing download/convert path; a Hub
   drafter at an immutable commit into a staging directory; an explicit local
   drafter is validated, never replaced.
3. **Validate** -- required files, drafter metadata, vocabulary and target depth.
   Accelerated exports that need different target IR get a *derived* directory;
   the ordinary target is never modified.
4. Record a manifest. Activation (load + warm-up) belongs to the model owner.

Acquisition failures (:class:`PreparationError`) let ``mode: auto`` fall back to
plain generation; incompatibility (:class:`CompatibilityError`) always fails.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from components.vlm.text_gen_profiles import (
    DFLASH_TARGET_RT_INFO_KEY,
    SpeculativeConfigError,
    SpeculativeSettings,
    SpeculativeUnavailableError,
    TextGenPlan,
    preconverted_repo,
    resolve_plan,
    version_at_least,
)
from utils.model_paths import OPENVINO_MODELS_DIR, SC_ROOT

logger = logging.getLogger(__name__)

_CONTENT_SEARCH_DIR = SC_ROOT / "content_search"
HF_SOURCES_DIR = SC_ROOT / "models" / "hf"
MANIFEST_DIR = OPENVINO_MODELS_DIR / ".manifests"

DOWNLOAD_ATTEMPTS = 3
LOCK_TIMEOUT_S = 3600.0
# Weights plus conversion intermediates; exports briefly hold source and IR.
EXPORT_DISK_FACTOR = 2.2

_LANGUAGE_MODEL_XML = ("openvino_language_model.xml", "openvino_model.xml")
# Revisions become path components and pins; only full commit hashes qualify.
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DRAFT_IR_FILES = ("openvino_model.xml", "openvino_model.bin", "config.json")
# Drafter checkpoint files fetched from the Hub: configuration and weights only,
# never repository code.
_DRAFT_SOURCE_PATTERNS = ["*.json", "*.safetensors"]

# optimum-intel ships DFlash drafter classes but selects them only through
# trust_remote_code; the export subprocess registers them instead, so no
# repository code can run. They are subclassed because optimum-intel treats
# classes defined under ``optimum.*`` as wrappers around another model.
_DFLASH_EXPORT = """\
import sys
from transformers import AutoModel, AutoModelForCausalLM, Qwen3Config
from optimum.exporters.openvino import model_patcher as mp
class DFlashDraftModel(mp.Qwen3DFlashDraftModel): pass
class DFlashForCausalLM(mp.Qwen3DFlashForCausalLM): pass
AutoModel.register(Qwen3Config, DFlashDraftModel, exist_ok=True)
AutoModelForCausalLM.register(Qwen3Config, DFlashForCausalLM, exist_ok=True)
from optimum.commands.optimum_cli import main
sys.argv = ["optimum-cli"] + sys.argv[1:]
main()
"""


class PreparationError(RuntimeError):
    """An artifact could not be acquired or produced (network, disk, export)."""


class CompatibilityError(PreparationError):
    """Artifacts exist but contradict each other or the selected profile."""


@dataclass
class PreparedSpeculative:
    settings: SpeculativeSettings
    target_dir: Path              # derived DFlash target, or the ordinary one
    draft_dir: Path               # external drafter IR
    draft_revision: Optional[str]


@dataclass
class PreparedArtifacts:
    plan: TextGenPlan
    target_dir: Path
    speculative: Optional[PreparedSpeculative] = None
    # Sanitized reason the requested acceleration is not available.
    speculative_error: Optional[str] = None
    timings: dict = field(default_factory=dict)
    manifest: Optional[Path] = None


def _installed_version(distribution: str) -> Optional[str]:
    try:
        from importlib.metadata import version

        return version(distribution)
    except Exception:  # noqa: BLE001 - not installed / unreadable metadata
        return None


def installed_genai_version() -> Optional[str]:
    return _installed_version("openvino-genai")


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------
def prepare(plan: TextGenPlan, *,
            genai_version: Optional[Callable[[], Optional[str]]] = None) -> PreparedArtifacts:
    """Prepare the plan's artifacts; raises on target failure.

    A speculative acquisition failure is an error under ``mode: "on"``;
    otherwise it is reported in ``speculative_error`` for plain fallback.
    """
    timings: dict = {}
    t0 = time.monotonic()
    target_dir = _prepare_target(plan)
    timings["target_s"] = round(time.monotonic() - t0, 3)

    result = PreparedArtifacts(plan=plan, target_dir=target_dir, timings=timings)
    strict = plan.mode == "on"
    if plan.wants_speculative:
        t1 = time.monotonic()
        try:
            _check_runtime(plan.speculative, (genai_version or installed_genai_version)())
            result.speculative = _prepare_speculative(plan, target_dir)
        except CompatibilityError:
            raise
        except (PreparationError, SpeculativeUnavailableError) as exc:
            if strict:
                raise
            result.speculative_error = str(exc)
            logger.warning("Speculative artifacts unavailable; plain generation will be "
                           "used: %s", exc)
        timings["speculative_s"] = round(time.monotonic() - t1, 3)
    elif plan.plain_reason:
        result.speculative_error = plan.plain_reason

    result.manifest = _write_manifest(result)
    return result


def _check_runtime(settings: SpeculativeSettings, installed: Optional[str]) -> None:
    need = settings.profile.min_genai_version
    if not version_at_least(installed, need):
        raise SpeculativeUnavailableError(
            f"{settings.method} needs openvino-genai >= {need} "
            f"(installed: {installed or 'unknown'})"
        )


# ----------------------------------------------------------------------------
# Target
# ----------------------------------------------------------------------------
def _convert_helpers():
    if str(_CONTENT_SEARCH_DIR) not in sys.path:
        sys.path.append(str(_CONTENT_SEARCH_DIR))
    from components.vlm.vlm_openvino_serving.utils.utils import convert_model, is_model_ready

    return convert_model, is_model_ready


def _prepare_target(plan: TextGenPlan) -> Path:
    model_dir = plan.target_dir
    convert_model, is_model_ready = _convert_helpers()
    if not is_model_ready(model_dir, require_detokenizer=True):
        model_dir.mkdir(parents=True, exist_ok=True)
        with ArtifactLock(model_dir):
            if not is_model_ready(model_dir, require_detokenizer=True):
                logger.info("Preparing text_gen target %s (%s) at %s",
                            plan.model_name, plan.weight_format, _rel(model_dir))
                try:
                    convert_model(plan.model_name, str(model_dir), model_type="vlm",
                                  weight_format=plan.weight_format)
                except Exception as exc:  # noqa: BLE001 - surfaced with context
                    raise PreparationError(
                        f"text_gen target {plan.model_name} could not be prepared: {exc}"
                    ) from exc
        if not is_model_ready(model_dir, require_detokenizer=True):
            raise PreparationError(
                f"text_gen target {plan.model_name} is incomplete after preparation"
            )
    check_tokenizer_runtime(model_dir, _installed_version("openvino-tokenizers"))
    return model_dir


_TOKENIZERS_VERSION_RE = re.compile(rb'<openvino_tokenizers_version value="([^"]+)"')


def check_tokenizer_runtime(model_dir: Path, installed: Optional[str]) -> None:
    """Refuse a tokenizer IR exported by a newer openvino-tokenizers release.

    An older runtime crashes natively loading it (no Python exception), so the
    backend would otherwise exit silently while loading the pipeline.
    """
    try:
        found = _TOKENIZERS_VERSION_RE.search((model_dir / "openvino_tokenizer.xml").read_bytes())
    except OSError:
        return
    if not found or not installed:
        return
    exported = found.group(1).decode("ascii", "replace")
    release = ".".join(exported.split(".")[:2])
    if not version_at_least(installed, release):
        raise PreparationError(
            f"{_rel(model_dir)} was exported with openvino-tokenizers {release}, newer than "
            f"the installed {installed}; upgrade the backend venv "
            "(pip install -r requirements.txt) before loading this model"
        )


# ----------------------------------------------------------------------------
# Speculative artifacts
# ----------------------------------------------------------------------------
def _prepare_speculative(plan: TextGenPlan, target_dir: Path) -> PreparedSpeculative:
    settings = plan.speculative
    if settings.method == "dflash":
        draft_dir, revision = _prepare_external_draft(plan)
        validate_dflash_pair(target_dir, draft_dir, settings.num_assistant_tokens)
        derived = ensure_dflash_target(target_dir, draft_dir)
        return PreparedSpeculative(settings, derived, draft_dir, revision)
    # Only reachable if the catalog grows a method without a preparation adapter.
    raise SpeculativeUnavailableError(f"no preparation adapter for {settings.method}")


def _prepare_external_draft(plan: TextGenPlan) -> tuple:
    settings = plan.speculative
    draft_dir = settings.draft_dir()
    if settings.source == "local":
        if not draft_dir.is_dir():
            raise PreparationError(
                f"speculative.draft_model directory {settings.describe()} does not exist; "
                "local drafters are validated, never downloaded"
            )
        _require_files(draft_dir, _DRAFT_IR_FILES, "local drafter IR")
        return draft_dir, None

    repo = settings.draft_model
    recorded = _recorded_draft_revision(plan, repo)
    if _draft_ready(draft_dir):
        revision = _read_json(draft_dir / ".prepared.json").get("revision")
        pinned = settings.draft_revision or recorded
        if pinned and revision and pinned != revision:
            _set_aside(draft_dir, "superseded")
        else:
            return draft_dir, revision or pinned

    draft_dir.parent.mkdir(parents=True, exist_ok=True)
    with ArtifactLock(draft_dir):
        if _draft_ready(draft_dir):
            return draft_dir, _read_json(draft_dir / ".prepared.json").get("revision")
        revision = settings.draft_revision or recorded or _with_retries(
            lambda: _resolve_revision(repo), f"revision of {repo}")
        source_dir = _download_source(repo, revision)
        _export_draft(source_dir, draft_dir, settings, repo, revision)
    return draft_dir, revision


def _draft_ready(draft_dir: Path) -> bool:
    return (draft_dir / ".prepared.json").is_file() and all(
        (draft_dir / f).is_file() for f in _DRAFT_IR_FILES)


def _download_source(repo: str, revision: str) -> Path:
    if not _COMMIT_RE.match(str(revision)):
        raise PreparationError(f"refusing non-commit revision for {repo}")
    final = HF_SOURCES_DIR / repo.replace("/", "__") / revision
    if (final / "config.json").is_file():
        return final
    staging = final.with_name(final.name + ".partial")
    staging.mkdir(parents=True, exist_ok=True)
    _check_disk(staging, _with_retries(lambda: _repo_size(repo, revision),
                                       f"size of {repo}") * EXPORT_DISK_FACTOR)
    logger.info("Downloading drafter source %s@%s", repo, revision[:12])
    # Resumable: snapshot_download skips files already complete in local_dir.
    _with_retries(lambda: _snapshot(repo, staging, revision, _DRAFT_SOURCE_PATTERNS),
                  f"{repo}@{revision[:12]}")
    if not (staging / "config.json").is_file():
        raise PreparationError(f"{repo}@{revision[:12]} has no config.json")
    staging.replace(final)
    return final


def _export_draft(source_dir: Path, draft_dir: Path, settings: SpeculativeSettings,
                  repo: str, revision: str) -> None:
    """Convert a drafter checkpoint to IR through the profile's recipe.

    No ``--trust-remote-code``: repository code is never executed (see
    ``_DFLASH_EXPORT``). A checkpoint the installed exporter cannot convert
    fails here, which ``auto`` reports as a plain fallback.
    """
    staging = draft_dir.with_name(draft_dir.name + ".partial")
    if staging.exists():
        shutil.rmtree(staging)
    fmt = settings.profile.draft_export_weight_format or "int4"
    # The interpreter's own environment; -X utf8 keeps the exporter's progress
    # output printable on non-UTF-8 consoles. --all-layers as the reference draft.
    cmd = [sys.executable, "-I", "-X", "utf8", "-c", _DFLASH_EXPORT,
           "export", "openvino", "--model", str(source_dir),
           "--task", "text-generation-with-past", "--weight-format", fmt, "--all-layers",
           str(staging)]
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"   # convert only what was downloaded and pinned
    logger.info("Exporting drafter %s to OpenVINO IR (%s)", repo, fmt)
    completed = subprocess.run(cmd, env=env, check=False)
    if completed.returncode != 0:
        raise PreparationError(
            f"drafter export of {repo} failed (exit {completed.returncode}); it needs "
            "optimum-intel>=2.2.0 (pip install -r requirements.txt)"
        )
    source_cfg = _read_json(source_dir / "config.json")
    exported_cfg = _read_json(staging / "config.json")
    if "dflash_config" in source_cfg and "dflash_config" not in exported_cfg:
        # The drafter metadata the runtime and validation read; copied into
        # our own derived directory, never into the source snapshot.
        exported_cfg["dflash_config"] = source_cfg["dflash_config"]
        _write_json(staging / "config.json", exported_cfg)
    _require_files(staging, _DRAFT_IR_FILES, f"exported drafter {repo}")
    _write_json(staging / ".prepared.json", {
        "repo": repo,
        "revision": revision,
        "weight_format": fmt,
        "exported_at": _now(),
        "files": _file_sizes(staging),
    })
    if draft_dir.exists():
        _set_aside(draft_dir, "invalid")
    staging.replace(draft_dir)


# ----------------------------------------------------------------------------
# DFlash compatibility and the derived target
# ----------------------------------------------------------------------------
def _model_config(model_dir: Path) -> dict:
    cfg = _read_json(model_dir / "config.json")
    text = cfg.get("text_config")
    return text if isinstance(text, dict) and text else cfg


def dflash_settings(draft_dir: Path) -> dict:
    section = _read_json(draft_dir / "config.json").get("dflash_config")
    return section if isinstance(section, dict) else {}


def validate_dflash_pair(target_dir: Path, draft_dir: Path, k: int) -> list:
    """Check drafter metadata against the target; returns the target layer ids."""
    section = dflash_settings(draft_dir)
    layer_ids = section.get("target_layer_ids")
    if (not isinstance(layer_ids, list) or not layer_ids
            or any(not isinstance(i, int) or isinstance(i, bool) or i < 0 for i in layer_ids)
            or len(set(layer_ids)) != len(layer_ids)):
        raise CompatibilityError(
            "drafter config.json must declare dflash_config.target_layer_ids as unique "
            "non-negative integers"
        )
    target_cfg = _model_config(target_dir)
    depth = target_cfg.get("num_hidden_layers")
    if isinstance(depth, int) and max(layer_ids) >= depth:
        raise CompatibilityError(
            f"drafter reads target layer {max(layer_ids)} but the target has {depth} layers; "
            "the drafter belongs to a different model"
        )
    draft_vocab = _model_config(draft_dir).get("vocab_size")
    target_vocab = target_cfg.get("vocab_size")
    if isinstance(draft_vocab, int) and isinstance(target_vocab, int) and draft_vocab != target_vocab:
        raise CompatibilityError(
            f"drafter vocabulary ({draft_vocab}) does not match the target ({target_vocab})"
        )
    block_size = section.get("block_size")
    if isinstance(block_size, int) and not isinstance(block_size, bool) and block_size > 1:
        if k > block_size - 1:
            raise CompatibilityError(
                f"num_assistant_tokens={k} exceeds the drafter's block_size {block_size} "
                f"minus the seed token (max {block_size - 1})"
            )
    return layer_ids


def target_language_xml(target_dir: Path) -> Path:
    for name in _LANGUAGE_MODEL_XML:
        if (target_dir / name).is_file():
            return target_dir / name
    raise CompatibilityError(f"no language-model IR in {_rel(target_dir)}")


def has_model_rt_info(xml_path: Path, key: str) -> bool:
    """Whether the IR's model-level ``<rt_info>`` (a direct child of ``<net>``) has ``key``."""
    depth = 0
    in_model_rt_info = False
    for event, elem in ET.iterparse(str(xml_path), events=("start", "end")):
        if event == "start":
            depth += 1
            if depth == 2 and elem.tag == "rt_info":
                in_model_rt_info = True
            elif in_model_rt_info and depth == 3 and elem.tag == key:
                return True
        else:
            if depth == 2 and elem.tag == "rt_info":
                in_model_rt_info = False
            depth -= 1
            if depth >= 2:
                elem.clear()
    return False


def dflash_layer_annotation(root: ET.Element, layer_ids: list) -> str:
    """GenAI's hidden-state locator: each target layer's final residual Add."""
    layers_node = root.find("layers")
    if layers_node is None:
        raise CompatibilityError("target IR has no <layers> section")
    located = {}
    for layer_id in layer_ids:
        suffix = f"layers.{layer_id}/aten::add/Add_1"
        matches = [l for l in layers_node.findall("layer")
                   if (l.get("name") or "").endswith(suffix)]
        if len(matches) != 1:
            raise CompatibilityError(
                f"target layer {layer_id}: expected one residual node ending in {suffix!r}, "
                f"found {len(matches)}"
            )
        port = matches[0].find("output/port")
        rank = len(port.findall("dim")) if port is not None else 0
        if rank != 3:
            raise CompatibilityError(f"target layer {layer_id} residual has rank {rank}, not 3")
        located[str(layer_id)] = {"producer": matches[0].get("name"), "output_index": 0}
    return json.dumps({"layers": located}, separators=(",", ":"))


def ensure_dflash_target(target_dir: Path, draft_dir: Path) -> Path:
    """Return a target directory whose IR carries the DFlash hidden-state metadata.

    A current export already has it and is used as-is. An older one gets a
    derived sibling ``<weight>-dflash``: weights hard-linked (copied if the
    filesystem cannot link), language-model XML annotated through ElementTree.
    The ordinary target stays byte-identical for plain generation.
    """
    xml_path = target_language_xml(target_dir)
    if has_model_rt_info(xml_path, DFLASH_TARGET_RT_INFO_KEY):
        return target_dir

    derived = target_dir.with_name(target_dir.name + "-dflash")
    source_hash = sha256_file(xml_path)
    stamp = _read_json(derived / ".derived.json")
    if stamp.get("source_xml_sha256") == source_hash and (derived / xml_path.name).is_file():
        return derived

    layer_ids = validate_dflash_pair(target_dir, draft_dir, 1)
    with ArtifactLock(derived):
        if derived.exists():
            _set_aside(derived, "stale")
        staging = derived.with_name(derived.name + ".partial")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        files = [p for p in target_dir.rglob("*") if p.is_file() and p != xml_path
                 and not p.name.startswith(".")]
        _check_disk(staging, 0 if _can_hardlink(target_dir, staging)
                    else sum(p.stat().st_size for p in files))
        for src in files:
            dst = staging / src.relative_to(target_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        annotation = dflash_layer_annotation(root, layer_ids)
        rt_info = root.find("rt_info")
        if rt_info is None:
            rt_info = ET.SubElement(root, "rt_info")
        ET.SubElement(rt_info, DFLASH_TARGET_RT_INFO_KEY, {"value": annotation})
        out_xml = staging / xml_path.name
        tree.write(str(out_xml), encoding="utf-8", xml_declaration=True)
        _write_json(staging / ".derived.json", {
            "source": _rel(target_dir),
            "source_xml_sha256": source_hash,
            "derived_xml_sha256": sha256_file(out_xml),
            "rt_info_key": DFLASH_TARGET_RT_INFO_KEY,
            "target_layer_ids": layer_ids,
            "created_at": _now(),
        })
        staging.replace(derived)
    logger.info("Derived DFlash target %s from %s", _rel(derived), _rel(target_dir))
    return derived


def _can_hardlink(src_dir: Path, dst_dir: Path) -> bool:
    try:
        return os.stat(src_dir).st_dev == os.stat(dst_dir).st_dev
    except OSError:
        return False


# ----------------------------------------------------------------------------
# Hub access, locking, files
# ----------------------------------------------------------------------------
def _snapshot(repo: str, local_dir: Path, revision: Optional[str], allow_patterns=None):
    from huggingface_hub import snapshot_download

    return snapshot_download(repo_id=repo, revision=revision, local_dir=str(local_dir),
                             allow_patterns=allow_patterns)


def _resolve_revision(repo: str) -> str:
    from huggingface_hub import HfApi

    sha = HfApi().model_info(repo).sha
    if not sha or not _COMMIT_RE.match(sha):
        raise PreparationError(f"could not resolve an immutable revision for {repo}")
    logger.warning("No pinned revision for %s in the catalog; using current commit %s "
                   "and recording it in the manifest", repo, sha[:12])
    return sha


def _repo_size(repo: str, revision: str) -> int:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    return sum(int(getattr(s, "size", 0) or 0) for s in (info.siblings or []))


def _with_retries(fn, what: str, attempts: int = DOWNLOAD_ATTEMPTS):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (PreparationError, KeyboardInterrupt):
            raise
        except Exception as exc:  # noqa: BLE001 - network/hub errors are retried
            last = exc
            logger.warning("Fetching %s failed (attempt %d/%d): %s", what, attempt,
                           attempts, exc)
            if attempt < attempts:
                time.sleep(min(30, 5 * attempt))
    raise PreparationError(f"could not fetch {what}: {last}") from last


def _check_disk(path: Path, needed_bytes: float) -> None:
    if not needed_bytes:
        return
    free = shutil.disk_usage(str(path)).free
    if free < needed_bytes:
        raise PreparationError(
            f"insufficient disk space: {needed_bytes / 2**30:.1f} GiB needed, "
            f"{free / 2**30:.1f} GiB free"
        )


class ArtifactLock:
    """Exclusive per-artifact lock file so concurrent starts do not interleave."""

    def __init__(self, artifact: Path, timeout_s: float = LOCK_TIMEOUT_S) -> None:
        self.path = artifact.with_name(artifact.name + ".lock")
        self.timeout_s = timeout_s
        self._fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError:
                if self._stale():
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise PreparationError(f"timed out waiting for {self.path.name}")
                time.sleep(2.0)

    def _stale(self) -> bool:
        try:
            pid = int(self.path.read_text(encoding="ascii").strip() or "0")
        except (OSError, ValueError):
            return False
        if pid == os.getpid():
            return False
        try:
            import psutil

            return not psutil.pid_exists(pid)
        except ImportError:
            return False

    def __exit__(self, *exc):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except OSError:
            pass
        return False


def _set_aside(path: Path, why: str) -> None:
    """Move an artifact out of the active path instead of deleting it (rollback)."""
    target = path.with_name(f"{path.name}.{why}-{datetime.now():%Y%m%d%H%M%S}")
    path.replace(target)
    logger.warning("Moved %s aside to %s", _rel(path), _rel(target))


def _require_files(directory: Path, names, what: str) -> None:
    missing = [n for n in names if not (directory / n).is_file()]
    if missing:
        raise PreparationError(f"{what} is missing {', '.join(missing)}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_sizes(directory: Path) -> dict:
    return {str(p.relative_to(directory)).replace("\\", "/"): p.stat().st_size
            for p in sorted(directory.rglob("*")) if p.is_file() and not p.name.startswith(".")}


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _rel(path: Path) -> str:
    """Root-relative path for logs and manifests; never a user's absolute path."""
    try:
        return str(Path(path).resolve().relative_to(SC_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return Path(path).name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------
# Manifest
# ----------------------------------------------------------------------------
def manifest_path(plan: TextGenPlan) -> Path:
    return MANIFEST_DIR / f"{plan.target_dir.parent.name}-{plan.weight_format}.json"


def _recorded_draft_revision(plan: TextGenPlan, repo: Optional[str]) -> Optional[str]:
    spec = _read_json(manifest_path(plan)).get("speculative") or {}
    if repo and str(spec.get("draft_model", "")).lower() == repo.lower():
        revision = spec.get("draft_revision")
        return revision if isinstance(revision, str) and _COMMIT_RE.match(revision) else None
    return None


def _write_manifest(result: PreparedArtifacts) -> Optional[Path]:
    plan = result.plan
    path = manifest_path(plan)
    previous = _read_json(path)
    data = {
        "schema_version": 1,
        "updated_at": _now(),
        "target": {
            "model": plan.model_name,
            "weight_format": plan.weight_format,
            "dir": _rel(result.target_dir),
            "repo": preconverted_repo(plan.model_name, plan.weight_format),
            # The existing download path does not record provenance; a legacy
            # cache is reused without claiming a revision nobody verified.
            "revision": None,
        },
        "speculative": {
            "mode": plan.mode,
            "requested_method": plan.requested_method,
            "status": "ready" if result.speculative else (
                "unavailable" if plan.mode != "off" else "off"),
            "reason": result.speculative_error,
        },
        "timings": result.timings,
    }
    spec = result.speculative
    if spec is not None:
        data["speculative"].update({
            "method": spec.settings.method,
            "draft_source": spec.settings.source,
            "draft_model": (spec.settings.draft_model
                            if spec.settings.source == "huggingface" else spec.settings.describe()),
            "draft_revision": spec.draft_revision,
            "num_assistant_tokens": spec.settings.num_assistant_tokens,
            "draft_dir": _rel(spec.draft_dir),
            "target_dir": _rel(spec.target_dir),
        })
    elif isinstance(previous.get("speculative"), dict) and previous["speculative"].get("draft_revision"):
        # Keep the recorded pin so a later accelerated start reuses it.
        for key in ("method", "draft_source", "draft_model", "draft_revision"):
            if key in previous["speculative"]:
                data["speculative"].setdefault(key, previous["speculative"][key])
    try:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(path, data)
        return path
    except OSError as exc:
        logger.warning("Could not write text_gen manifest: %s", exc)
        return None
