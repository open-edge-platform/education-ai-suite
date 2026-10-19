# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Serving catalog and ``models.text_gen.speculative`` resolution.

Pure data and validation -- no OpenVINO import -- so the launcher, the warm VLM
and the tests share one decision. :func:`resolve_plan` turns the ``text_gen``
config node into a :class:`TextGenPlan`:

* the **target** stays selected by ``vlm_name`` + ``weight_format``; a model the
  catalog does not know keeps the existing plain loading path untouched;
* the optional **speculative** block selects an activation policy (``mode``),
  a mechanism (``method``) and draft artifacts. Invalid settings raise
  :class:`SpeculativeConfigError`; they never trigger a fallback. A recognized
  method without a qualified profile becomes plain generation under
  ``mode: auto`` and an actionable failure under ``mode: "on"``.

The only speculative profile is DFlash for Qwen3.6-35B-A3B INT4. ``dflash2``
and ``mtp`` stay valid settings without a profile: plain generation under
``auto``, an actionable failure under ``"on"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping, Optional

from utils.model_paths import OPENVINO_MODELS_DIR, SC_ROOT, openvino_model_dir

MODES = ("off", "auto", "on")
METHODS = ("auto", "dflash", "dflash2", "mtp")
DRAFT_SOURCES = ("huggingface", "local", "target")
SPECULATIVE_KEYS = frozenset({
    "mode", "method", "draft_source", "draft_model", "draft_revision", "num_assistant_tokens",
})

# Target rt_info GenAI reads to locate the hidden states a DFlash drafter consumes.
DFLASH_TARGET_RT_INFO_KEY = "hidden_states_decoder_layers"

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class SpeculativeConfigError(ValueError):
    """``models.text_gen.speculative`` is malformed or contradicts the catalog."""


class UnsupportedRequestError(ValueError):
    """A request the active pipeline cannot honor; rejected before generation.

    Raised instead of silently changing the request (for example sampling on a
    greedy-only speculative pipeline, or tools on a model without tool support).
    """


@dataclass(frozen=True)
class SpeculativeProfile:
    """One target/method combination the serving runtime knows how to load."""

    method: str
    precisions: tuple = ("int4", "int8")
    default_source: str = "huggingface"
    draft_repo: Optional[str] = None
    # Immutable Hub commit. ``None`` until a maintainer pins one: preparation
    # then resolves the current commit once, records it in the manifest and
    # reuses that pin on every later start.
    draft_revision: Optional[str] = None
    # Recipe turning the downloaded drafter checkpoint into runtime IR.
    draft_export_weight_format: Optional[str] = None
    num_assistant_tokens: int = 3
    num_assistant_tokens_range: tuple = (1, 15)
    min_genai_version: str = "2026.3"
    ov_properties: Mapping = field(default_factory=dict)
    scheduler: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class TargetProfile:
    name: str
    # weight_format -> pre-converted OpenVINO IR repository
    ir_repos: Mapping
    tool_calls: bool = False
    # Method ``auto`` resolves to this; it is never chosen by trial loading.
    default_method: Optional[str] = None
    methods: Mapping = field(default_factory=dict)


_GPU_PAGED = {"GPU_ENABLE_LARGE_ALLOCATIONS": "YES", "KV_CACHE_PRECISION": "f16"}

# Values from the pinned context_bench configuration (config_qwen3.6_35b.yaml).
# cache_size is left runtime-managed: classroom prompts vary far more than the
# fixed 8K benchmark context.
_QWEN36_DFLASH = SpeculativeProfile(
    method="dflash",
    precisions=("int4",),
    draft_repo="z-lab/Qwen3.6-35B-A3B-DFlash",
    draft_revision="f181eece646affea2c38b2765f1aaa01a9734ccd",
    draft_export_weight_format="int4",
    # k=3 was best for classroom summaries at 8K; k=7 for code/math.
    num_assistant_tokens=3,
    # block_size 16 includes the seed token, and the 17 linear-attention rows
    # cover max_num_seqs + k + 1 up to k=15.
    num_assistant_tokens_range=(1, 15),
    min_genai_version="2026.3",
    ov_properties=_GPU_PAGED,
    scheduler={
        "max_num_batched_tokens": 65536,
        "max_num_seqs": 1,
        "num_linear_attention_blocks": 17,
        "enable_prefix_caching": False,
    },
)

CATALOG: Mapping[str, TargetProfile] = {
    "qwen/qwen3-vl-8b-instruct": TargetProfile(
        name="Qwen/Qwen3-VL-8B-Instruct",
        ir_repos={"int4": "OpenVINO/Qwen3-VL-8B-Instruct-int4-ov",
                  "int8": "OpenVINO/Qwen3-VL-8B-Instruct-int8-ov"},
        tool_calls=True,
    ),
    "qwen/qwen3.5-9b": TargetProfile(
        name="Qwen/Qwen3.5-9B",
        ir_repos={"int4": "OpenVINO/Qwen3.5-9B-int4-ov",
                  "int8": "OpenVINO/Qwen3.5-9B-int8-ov"},
        tool_calls=True,
    ),
    "qwen/qwen3.6-35b-a3b": TargetProfile(
        name="Qwen/Qwen3.6-35B-A3B",
        ir_repos={"int4": "OpenVINO/Qwen3.6-35B-A3B-int4-ov"},
        tool_calls=True,
        default_method="dflash",
        methods={"dflash": _QWEN36_DFLASH},
    ),
    "qwen/qwen3.8-27b": TargetProfile(
        name="Qwen/Qwen3.8-27B",
        ir_repos={"int4": "OpenVINO/Qwen3.8-27B-int4-ov",
                  "int8": "OpenVINO/Qwen3.8-27B-int8-ov"},
        tool_calls=True,
    ),
}


def target_profile(model_name) -> Optional[TargetProfile]:
    return CATALOG.get(str(model_name).strip().lower())


def preconverted_repo(model_name, weight_format) -> Optional[str]:
    profile = target_profile(model_name)
    if profile is None:
        return None
    return profile.ir_repos.get(str(weight_format).lower())


@dataclass(frozen=True)
class SpeculativeSettings:
    """Resolved, validated speculative selection for one target."""

    method: str
    source: str
    draft_model: Optional[str]          # Hub repo id or local directory
    draft_revision: Optional[str]       # explicit/pinned commit; None = resolve once
    num_assistant_tokens: int
    profile: SpeculativeProfile

    def draft_dir(self) -> Optional[Path]:
        """Runtime IR directory of the drafter."""
        if self.source == "local":
            return resolve_local_dir(self.draft_model)
        if self.source == "huggingface" and self.draft_model:
            fmt = self.profile.draft_export_weight_format or "int4"
            return OPENVINO_MODELS_DIR / self.draft_model.split("/")[-1] / fmt
        return None

    def describe(self) -> str:
        """Identity safe for health/logs: no local paths."""
        if self.source == "local":
            return f"local IR ({Path(str(self.draft_model)).name})"
        rev = f"@{self.draft_revision[:12]}" if self.draft_revision else ""
        return f"{self.draft_model}{rev}"


@dataclass(frozen=True)
class TextGenPlan:
    model_name: str
    weight_format: str
    device: str
    target_dir: Path
    target: Optional[TargetProfile]
    mode: str
    requested_method: Optional[str]
    speculative: Optional[SpeculativeSettings]
    # Why the plan is plain although speculation was requested.
    plain_reason: Optional[str] = None

    @property
    def wants_speculative(self) -> bool:
        return self.mode != "off" and self.speculative is not None

    @property
    def tool_calls_declared(self) -> Optional[bool]:
        return self.target.tool_calls if self.target is not None else None

    def without_speculative(self, reason: str) -> "TextGenPlan":
        return replace(self, speculative=None, plain_reason=reason)


def resolve_local_dir(value) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else (SC_ROOT / path)


def _get(node, key, default=None):
    if isinstance(node, Mapping):
        return node.get(key, default)
    return getattr(node, key, default)


def _as_mapping(node) -> Optional[dict]:
    if node is None:
        return None
    if isinstance(node, Mapping):
        return dict(node)
    if hasattr(node, "__dict__"):
        return dict(vars(node))
    raise SpeculativeConfigError(
        "models.text_gen.speculative must be a mapping of speculative settings"
    )


def _mode(value) -> str:
    # YAML 1.1 reads bare off/on as booleans; accept them for the policy field.
    if value is None:
        return "off"
    if value is False:
        return "off"
    if value is True:
        return "on"
    text = str(value).strip().lower()
    if text not in MODES:
        raise SpeculativeConfigError(
            f"speculative.mode must be one of {', '.join(MODES)} (got {value!r})"
        )
    return text


def _choice(key, value, allowed, default):
    if value is None:
        return default
    text = str(value).strip().lower()
    if text not in allowed:
        raise SpeculativeConfigError(
            f"speculative.{key} must be one of {', '.join(allowed)} (got {value!r})"
        )
    return text


def _optional_str(key, value) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SpeculativeConfigError(f"speculative.{key} must be a non-empty string or null")
    return value.strip()


def resolve_plan(text_gen) -> TextGenPlan:
    """Resolve ``models.text_gen`` into a validated serving plan."""
    if text_gen is None:
        raise ValueError("models.text_gen is not configured")
    model_name = str(_get(text_gen, "vlm_name"))
    weight_format = str(_get(text_gen, "weight_format")).lower()
    device = str(_get(text_gen, "device", "GPU")).upper()
    target = target_profile(model_name)
    base = dict(
        model_name=model_name,
        weight_format=weight_format,
        device=device,
        target_dir=openvino_model_dir(model_name, weight_format),
        target=target,
    )

    raw = _as_mapping(_get(text_gen, "speculative"))
    if raw is None:
        return TextGenPlan(mode="off", requested_method=None, speculative=None, **base)

    mode = _mode(raw.get("mode"))
    if mode == "off":
        # Dormant fields are ignored entirely: only the target is prepared.
        return TextGenPlan(mode="off", requested_method=None, speculative=None, **base)

    unknown = set(raw) - SPECULATIVE_KEYS
    if unknown:
        raise SpeculativeConfigError(
            "unknown speculative key(s): " + ", ".join(sorted(map(str, unknown)))
            + "; supported: " + ", ".join(sorted(SPECULATIVE_KEYS))
        )
    method = _choice("method", raw.get("method"), METHODS, "auto")
    source = _choice("draft_source", raw.get("draft_source"), DRAFT_SOURCES, None)
    draft_model = _optional_str("draft_model", raw.get("draft_model"))
    revision = _optional_str("draft_revision", raw.get("draft_revision"))
    tokens = raw.get("num_assistant_tokens")
    if tokens is not None and (isinstance(tokens, bool) or not isinstance(tokens, int)
                               or tokens < 1):
        raise SpeculativeConfigError(
            f"speculative.num_assistant_tokens must be a positive integer or null (got {tokens!r})"
        )
    if revision is not None and not _COMMIT_RE.match(revision.lower()):
        raise SpeculativeConfigError(
            "speculative.draft_revision must be a full 40-character commit hash "
            "(branches and tags are mutable)"
        )
    _check_source_shape(method, source, draft_model, revision)

    resolved_method = method
    if method == "auto":
        resolved_method = target.default_method if target else None
        if resolved_method is None:
            return _unqualified(base, mode, method, (
                f"{model_name} has no catalog-declared speculative method; "
                "it continues with plain generation"
            ))

    profile = target.methods.get(resolved_method) if target else None
    if profile is None:
        return _unqualified(base, mode, method, (
            f"no qualified {resolved_method} profile for {model_name}"
        ))

    source = source or profile.default_source
    # Re-check with the defaults filled in (method auto -> concrete method).
    _check_source_shape(resolved_method, source, draft_model, revision)
    if source == "huggingface":
        if draft_model is None:
            draft_model = profile.draft_repo
        elif profile.draft_repo is None or draft_model.lower() != profile.draft_repo.lower():
            raise SpeculativeConfigError(
                f"speculative.draft_model {draft_model!r} is not the qualified {resolved_method} "
                f"drafter for {model_name} (expected {profile.draft_repo!r})"
            )
        revision = revision or profile.draft_revision

    k = tokens if tokens is not None else profile.num_assistant_tokens
    low, high = profile.num_assistant_tokens_range
    if not low <= k <= high:
        raise SpeculativeConfigError(
            f"speculative.num_assistant_tokens={k} is outside the {resolved_method} "
            f"profile's supported range {low}..{high}"
        )

    settings = SpeculativeSettings(
        method=resolved_method,
        source=source,
        draft_model=draft_model,
        draft_revision=revision,
        num_assistant_tokens=k,
        profile=profile,
    )
    if weight_format not in profile.precisions:
        return _unqualified(base, mode, method, (
            f"{resolved_method} is not qualified for {model_name} {weight_format} "
            f"(qualified: {', '.join(profile.precisions)})"
        ))
    return TextGenPlan(mode=mode, requested_method=method, speculative=settings, **base)


def _check_source_shape(method, source, draft_model, revision) -> None:
    """Reject contradictory method/source/model/revision combinations."""
    if source == "target" and method not in ("mtp", "auto"):
        raise SpeculativeConfigError(
            "speculative.draft_source: target is valid only with method: mtp"
        )
    if method == "mtp":
        if source not in (None, "target"):
            raise SpeculativeConfigError(
                "MTP uses the target's bundled prediction head; draft_source must be "
                "target (or null), not an external drafter"
            )
        if draft_model is not None:
            raise SpeculativeConfigError(
                "MTP uses the target's bundled prediction head; draft_model must be null"
            )
    if source in ("local", "target") and revision is not None:
        raise SpeculativeConfigError(
            f"speculative.draft_revision must be null for draft_source: {source}"
        )
    if source == "local" and draft_model is None:
        raise SpeculativeConfigError(
            "speculative.draft_source: local requires draft_model to name an existing "
            "OpenVINO IR directory"
        )
    if source == "target" and draft_model is not None:
        raise SpeculativeConfigError(
            "speculative.draft_source: target requires draft_model: null"
        )


def _unqualified(base: dict, mode: str, method: str, reason: str) -> TextGenPlan:
    if mode == "on":
        raise SpeculativeUnavailableError(
            f"{reason}. speculative.mode is \"on\", which requires acceleration; "
            "set mode: auto to allow plain fallback or mode: \"off\" for plain generation"
        )
    return TextGenPlan(mode=mode, requested_method=method, speculative=None,
                       plain_reason=reason, **base)


class SpeculativeUnavailableError(RuntimeError):
    """``mode: "on"`` was requested but the selected acceleration cannot run."""


def version_at_least(installed: Optional[str], required: str) -> bool:
    """Compare leading numeric release components (``2026.5.0.0.dev2026`` >= ``2026.5``)."""
    if not installed:
        return False

    def parts(text):
        out = []
        for piece in str(text).split("."):
            digits = re.match(r"\d+", piece)
            if not digits:
                break
            out.append(int(digits.group()))
        return out

    have, need = parts(installed), parts(required)
    width = max(len(have), len(need))
    return have + [0] * (width - len(have)) >= need + [0] * (width - len(need))
