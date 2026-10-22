# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0


from __future__ import annotations

import gc
import json
import logging
import math
import re
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

import openvino_genai as ov_genai
from transformers import AutoTokenizer

from components.vlm import text_gen_prepare
from components.vlm.text_gen_profiles import (
    SpeculativeSettings,
    UnsupportedRequestError,
    resolve_plan,
)
from utils.chat_prompt import render_chat_prompt, template_supports_tools
from utils.markdown_cleaner import StreamThinkFilter, strip_think_tokens
from utils.model_paths import openvino_model_dir
from utils.ov_genai_util import YieldingTextStreamer

logger = logging.getLogger(__name__)

_DEFAULT_MAX_NEW_TOKENS = 5120

# Per-request decoding parameters accepted through ``generate(sampling=...)``,
# named as in GenerationConfig and the OpenAI request.
SAMPLING_KEYS = ("top_p", "top_k", "repetition_penalty", "presence_penalty",
                 "frequency_penalty")

# Plain-mode decision retained for the process lifetime: once speculative
# activation failed under ``mode: auto``, a reload (after shutdown/eviction)
# does not try the failing drafter again.
_PLAIN_DECISION: Optional[str] = None

# Strip absolute local paths (drive, UNC, POSIX) from reasons surfaced through
# /health; Hub repo ids such as ``z-lab/<model>`` are kept.
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(?<![\w.-])/)[^\s'\"]+")


def _sanitize(text) -> str:
    return _PATH_RE.sub("<path>", str(text))[:300]


class VLMTextGen:
    """Warm ``ov_genai.VLMPipeline`` fronting the ``text_gen`` capability."""

    def __init__(self) -> None:
        self._pipe = None
        self.tokenizer = None
        self._model_name: Optional[str] = None
        self._device: Optional[str] = None
        self._weight_format: Optional[str] = None
        self._max_new_tokens: int = _DEFAULT_MAX_NEW_TOKENS
        self._plan = None
        # Active speculative settings; None means plain generation.
        self._speculative: Optional[SpeculativeSettings] = None
        self._tool_calls = False
        self._xml_tool_calls = False
        self._status: dict = {}
        self._load_config()
        self._load()

    @property
    def device(self) -> Optional[str]:
        return self._device

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    @property
    def weight_format(self) -> Optional[str]:
        return self._weight_format

    @property
    def supports_tools(self) -> bool:
        return self._tool_calls

    @property
    def decoding_method(self) -> str:
        return self._speculative.method if self._speculative else "plain"

    def _load_config(self) -> None:
        from utils.config_loader import config

        text_gen = getattr(config.models, "text_gen", None)
        if text_gen is None:
            raise ValueError(
                "models.text_gen is not configured; the warm VLM cannot start"
            )
        self._model_name = str(text_gen.vlm_name)
        self._device = str(text_gen.device).upper()
        self._weight_format = str(text_gen.weight_format).lower()
        self._max_new_tokens = int(
            getattr(text_gen, "max_new_tokens", _DEFAULT_MAX_NEW_TOKENS)
        )
        # Invalid speculative settings fail here, before any model work.
        self._plan = resolve_plan(text_gen)

    def _model_dir(self) -> Path:
        """Return the shared IR directory ``models/openvino/<name>/<weight>``."""
        return openvino_model_dir(self._model_name, self._weight_format)

    def _ov_config(self) -> dict:
        """Runtime config for the pipeline; large allocations help on GPU."""
        if self._device.startswith("GPU"):
            return {"GPU_ENABLE_LARGE_ALLOCATIONS": "YES"}
        return {}

    def _speculative_kwargs(self, settings: SpeculativeSettings, draft_dir: Path) -> dict:
        """Constructor arguments for the paged pipeline with a draft model."""
        profile = settings.profile
        kwargs = {
            key: value for key, value in profile.ov_properties.items()
            if self._device.startswith("GPU") or not key.startswith("GPU_")
        }
        scheduler = ov_genai.SchedulerConfig()
        for key, value in profile.scheduler.items():
            if not hasattr(scheduler, key):
                raise ValueError(f"Unsupported SchedulerConfig property: {key}")
            setattr(scheduler, key, value)
        kwargs["scheduler_config"] = scheduler
        kwargs["draft_model"] = ov_genai.draft_model(str(draft_dir), self._device)
        return kwargs

    def _load(self) -> None:
        global _PLAIN_DECISION
        plan = self._plan
        started = time.monotonic()
        prepared = text_gen_prepare.prepare(plan)
        timings = {"prepare_s": round(time.monotonic() - started, 3)}
        fallback = prepared.speculative_error
        spec = prepared.speculative
        if spec is not None and _PLAIN_DECISION is not None:
            fallback, spec = _PLAIN_DECISION, None

        if spec is not None:
            try:
                self._load_pipeline(spec.target_dir, spec.settings, spec.draft_dir, timings)
                self._speculative = spec.settings
            except Exception as exc:  # noqa: BLE001 - policy decides below
                if plan.mode == "on":
                    raise
                logger.warning(
                    "Speculative %s activation failed; falling back to plain "
                    "generation for this launch: %s", spec.settings.method, exc,
                )
                self._discard_pipeline()
                fallback = f"{spec.settings.method} activation failed: {_sanitize(exc)}"
                _PLAIN_DECISION = fallback

        if self._speculative is None:
            self._load_pipeline(prepared.target_dir, None, None, timings)

        self._status = self._build_status(spec, fallback, timings)
        logger.info("Warm VLM ready (decoding=%s).", self.decoding_method)

    def _load_pipeline(self, model_dir: Path, settings: Optional[SpeculativeSettings],
                       draft_dir: Optional[Path], timings: dict) -> None:
        logger.info(
            "Loading warm VLMPipeline: model=%s device=%s weight=%s decoding=%s",
            self._model_name,
            self._device,
            self._weight_format,
            settings.method if settings else "plain",
        )
        started = time.monotonic()
        if settings is None:
            self._pipe = ov_genai.VLMPipeline(
                str(model_dir), device=self._device, **self._ov_config()
            )
        else:
            self._speculative = settings  # generation config needs it for warm-up
            try:
                self._pipe = ov_genai.VLMPipeline(
                    str(model_dir), device=self._device,
                    **self._speculative_kwargs(settings, draft_dir),
                )
            except Exception:
                self._speculative = None
                raise
        timings["load_s"] = round(time.monotonic() - started, 3)
        try:
            # Think tags are ordinary vocabulary entries in every Qwen3 family,
            # so the streamer decodes them intact. Marking them special would
            # make skip_special_tokens drop the tags while keeping the reasoning
            # text between them, leaving nothing for StreamThinkFilter to match.
            self.tokenizer = AutoTokenizer.from_pretrained(
                str(model_dir), extra_special_tokens={}
            )
        except Exception as exc:
            logger.warning(
                "transformers AutoTokenizer failed (%s); falling back to the "
                "OpenVINO pipeline tokenizer.", exc
            )
            self.tokenizer = self._pipe.get_tokenizer()
        self._tool_calls = self._detect_tool_support()
        try:
            timings["warmup_s"] = self._warm_up()
        except Exception:
            self._speculative = None
            raise

    def _warm_up(self) -> float:
        """One short greedy generation before readiness is reported."""
        started = time.monotonic()
        config = self._generation_config(2, None)
        prompt = self._render([{"role": "user", "content": "Hello"}], config, None, False)
        self._pipe.generate(prompt, generation_config=config)
        return round(time.monotonic() - started, 3)

    def _detect_tool_support(self) -> bool:
        declared = self._plan.tool_calls_declared if self._plan else None
        renders_tools = template_supports_tools(self.tokenizer)
        if declared and not renders_tools:
            logger.warning("%s chat template does not render tools; tool calling disabled.",
                           self._model_name)
        # Qwen3.5+ templates ask for <function=...> XML calls, Qwen3 for JSON.
        self._xml_tool_calls = "<function=" in str(getattr(self.tokenizer, "chat_template", ""))
        return bool(renders_tools and declared is not False)

    def _call_opening(self, name: str) -> str:
        """Start of a call to ``name`` in this model's syntax; empty for any function."""
        if not name:
            return ""
        if self._xml_tool_calls:
            return f"<function={name}>\n"
        return '{"name": ' + json.dumps(name) + ', "arguments": '

    def _discard_pipeline(self) -> None:
        self._pipe = None
        self.tokenizer = None
        self._speculative = None
        gc.collect()

    def _build_status(self, requested, fallback: Optional[str], timings: dict) -> dict:
        plan = self._plan
        active = self._speculative
        settings = active or (requested.settings if requested else plan.speculative)
        speculative = {
            "requested_mode": plan.mode,
            "requested_method": plan.requested_method,
            "effective_method": self.decoding_method,
            "draft": settings.describe() if settings else None,
            "num_assistant_tokens": active.num_assistant_tokens if active else None,
            "fallback_reason": _sanitize(fallback) if fallback and not active else None,
        }
        return {
            "model": self._model_name,
            "weight_format": self._weight_format,
            "device": self._device,
            "tool_calls": self._tool_calls,
            "speculative": speculative,
            "warmup": {"status": "ok", "seconds": timings.get("warmup_s")},
            "startup": timings,
            "diagnostics": {
                "openvino_genai": text_gen_prepare.installed_genai_version(),
                "draft_revision": requested.draft_revision if requested else None,
                "scheduler": dict(active.profile.scheduler) if active else None,
            },
        }

    def status(self) -> dict:
        return dict(self._status)

    def release(self) -> None:
        """Release the resident pipeline and reclaim device/host memory."""
        try:
            self._pipe = None
            self.tokenizer = None
            gc.collect()
            logger.info("Warm VLM released and memory reclaimed.")
        except Exception:  # noqa: BLE001 - shutdown best-effort
            logger.warning("Failed to fully release warm VLM", exc_info=True)

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(
        self,
        prompt: Optional[str] = None,
        *,
        messages: Optional[list] = None,
        images: Optional[list] = None,
        stream: bool = True,
        max_new_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        enable_thinking: Optional[bool] = None,
        json_schema: Optional[str] = None,
        tools: Optional[list] = None,
        force_tool_call: Optional[str] = None,
        call=None,
        finish_info: Optional[dict] = None,
        sampling: Optional[dict] = None,
    ) -> Union[Iterator[str], str]:
        """Generate from a chat history using the warm pipeline.

        Mirrors ``TextGen.generate``: streaming yields decoded token chunks,
        non-streaming returns the full string.

        Pass ``messages`` (a chat history) or ``prompt`` (a single user turn),
        never both. Either way this method owns the templating, so callers must
        not run ``apply_chat_template`` themselves -- doing so would wrap the
        rendered string in a second user turn, burying the ``<think></think>``
        prefill and bringing reasoning back.

        ``images`` (a list of ``ov.Tensor`` frames, already decoded by the
        caller) enables the multimodal path used by content-search video
        summarization; when omitted the call is text-only.
        ``enable_thinking=False`` suppresses Qwen3 thinking and strips any
        reasoning that slips through; ``None`` keeps the model default.
        ``json_schema`` (a JSON-schema string) constrains decoding to output
        matching that schema.
        ``tools`` (OpenAI function definitions) is rendered through the
        model's tool-aware template; it requires a tool-capable model.
        ``force_tool_call`` starts the answer with a tool call: ``""`` for any
        offered function, or a function name. The prompt ends with the opening
        of the call in the model's own syntax (reasoning is closed first), and
        ``finish_info["prefill"]`` holds that text, which the output continues.
        ``call`` (a ``utils.processing_stats.ModelCall``) records timing, and
        ``finish_info`` receives token counts and truncation once generation
        ends.
        ``sampling`` sets per-request decoding parameters on top of the
        defaults: any of ``SAMPLING_KEYS``. Penalties also apply to greedy
        decoding; ``top_p``/``top_k`` only take effect when sampling.
        """
        if self._pipe is None:
            raise RuntimeError("VLM pipeline is not loaded")
        if (messages is None) == (prompt is None):
            raise ValueError("Provide exactly one of prompt or messages.")
        if messages is None:
            if not prompt.strip():
                raise ValueError("Invalid prompt provided.")
            messages = [{"role": "user", "content": prompt}]
        elif not messages:
            raise ValueError("Invalid messages provided.")
        if self._speculative is not None and temperature is not None and float(temperature) > 0.0:
            raise UnsupportedRequestError(
                f"temperature={temperature} requests sampling, but the active "
                f"{self._speculative.method} pipeline supports greedy decoding only; "
                "omit temperature or set it to 0"
            )
        unknown = set(sampling or ()) - set(SAMPLING_KEYS)
        if unknown:
            raise ValueError(f"Unsupported sampling parameters: {sorted(unknown)}")
        if self._speculative is not None and sampling:
            # Draft verification compares raw greedy picks; penalised logits
            # would make the target disagree with its own drafts.
            raise UnsupportedRequestError(
                f"{sorted(sampling)} are not supported by the active "
                f"{self._speculative.method} pipeline (greedy decoding only)"
            )
        if (tools or force_tool_call is not None) and not self._tool_calls:
            raise UnsupportedRequestError(f"{self._model_name} does not support tool calling")

        if call is not None:
            call.started()
        try:
            config = self._generation_config(max_new_tokens, temperature, json_schema, sampling)
            prompt = self._render(messages, config, enable_thinking, bool(images), tools)
            prefill = ""
            if force_tool_call is not None:
                prefill = "<tool_call>\n" + self._call_opening(force_tool_call)
                if prompt.rstrip().endswith("<think>"):
                    # The template's own form of a turn without reasoning.
                    prompt = prompt.rstrip() + "\n\n</think>\n\n"
                prompt += prefill
            if finish_info is not None:
                finish_info["max_new_tokens"] = config.max_new_tokens
                finish_info["reasoning_open"] = prompt.rstrip().endswith("<think>")
                finish_info["prefill"] = prefill

            if stream:
                think_filter = StreamThinkFilter() if enable_thinking is False else None
                return self._generate_stream(prompt, config, images, think_filter,
                                             call, finish_info)
            if images:
                result = self._pipe.generate(prompt, images=images, generation_config=config)
            else:
                result = self._pipe.generate(prompt, generation_config=config)
        except BaseException as exc:
            if call is not None:
                call.finish("failed", exc)
            raise
        self._record_result(result, config, call, finish_info)
        if call is not None:
            call.finish("ok")
        raw = str(result)
        return strip_think_tokens(raw) if enable_thinking is False else raw

    def _render(
        self,
        messages: list,
        config: "ov_genai.GenerationConfig",
        enable_thinking: Optional[bool],
        has_images: bool,
        tools: Optional[list] = None,
    ) -> str:
        """Render ``messages`` here rather than inside the pipeline.

        Keeping templating on this side means one engine and one set of rules
        for every caller. The pipeline only takes over for a model that has no
        chat template at all, where rendering is impossible.
        """
        try:
            prompt = render_chat_prompt(
                self.tokenizer,
                messages,
                self._model_name,
                enable_thinking,
                has_images,
                tools=tools,
            )
            config.apply_chat_template = False
            return prompt
        except Exception as exc:  # noqa: BLE001 - model without a chat template
            if tools or any(m.get("role") == "tool" or m.get("tool_calls") for m in messages):
                # The pipeline fallback would keep only the last turn and drop
                # the definitions and tool results silently.
                raise UnsupportedRequestError(
                    f"{self._model_name} chat template could not render this tool "
                    f"conversation: {_sanitize(exc)}"
                ) from exc
            logger.warning(
                "Chat template rendering failed (%s); letting the pipeline "
                "template the last user turn.", exc
            )
            config.apply_chat_template = True
            return str(messages[-1].get("content", ""))

    def _generation_config(
        self,
        max_new_tokens: Optional[int],
        temperature: Optional[float],
        json_schema: Optional[str] = None,
        sampling: Optional[dict] = None,
    ) -> "ov_genai.GenerationConfig":
        max_tokens = (
            int(max_new_tokens) if max_new_tokens is not None else self._max_new_tokens
        )
        kwargs = {"max_new_tokens": max_tokens, "do_sample": False}
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
            kwargs["do_sample"] = float(temperature) > 0.0
        for key, value in (sampling or {}).items():
            kwargs[key] = int(value) if key == "top_k" else float(value)
        config = ov_genai.GenerationConfig(**kwargs)
        if self._speculative is not None:
            # Greedy verification with a fixed draft window; the runtime owns
            # drafting and acceptance.
            config.num_return_sequences = 1
            config.num_assistant_tokens = self._speculative.num_assistant_tokens
            config.assistant_confidence_threshold = 0.0
        if json_schema:
            try:
                config.structured_output_config = ov_genai.StructuredOutputConfig(
                    json_schema=json_schema
                )
            except Exception as exc:  # noqa: BLE001 - runtime without a grammar backend
                logger.warning(
                    "Structured output unavailable (%s); generating unconstrained.", exc
                )
        return config

    def _record_result(self, result, config, call, finish_info) -> None:
        metrics = _perf_metrics(result)
        metrics["decoding"] = self.decoding_method
        if call is not None:
            call.update_runtime(metrics)
        if finish_info is not None:
            produced = metrics.get("output_tokens")
            finish_info["output_tokens"] = produced
            finish_info["input_tokens"] = metrics.get("input_tokens")
            reason = _finish_reason(result)
            if reason is not None:
                finish_info["truncated"] = reason == "LENGTH"
            else:
                finish_info["truncated"] = (
                    produced >= config.max_new_tokens if isinstance(produced, int) else None
                )

    def _generate_stream(
        self,
        prompt: str,
        config: "ov_genai.GenerationConfig",
        images: Optional[list] = None,
        think_filter: Optional[StreamThinkFilter] = None,
        call=None,
        finish_info: Optional[dict] = None,
    ) -> Iterator[str]:
        """Run generation on a worker thread, yielding tokens as they arrive.

        A memory/runtime error raised during generation is re-raised in the
        consuming thread once the queue drains, so the ``CapabilityRunner`` can
        surface it as an ``OomError`` while keeping the capability resident.
        """
        streamer = YieldingTextStreamer(self.tokenizer)

        def run_generation():
            streamer.generation_start_time = time.perf_counter()
            if images:
                result = self._pipe.generate(
                    prompt,
                    images=images,
                    generation_config=config,
                    streamer=streamer,
                )
            else:
                result = self._pipe.generate(
                    prompt, generation_config=config, streamer=streamer
                )
            self._record_result(result, config, call, finish_info)

        if call is not None:
            streamer.on_first_token = call.first_output
        stream = _TokenStream(streamer, think_filter, call)
        stream.start(run_generation)
        return stream


class _TokenStream:
    """Streamed tokens backed by a native generation thread.

    Closing the stream early (client disconnect) asks the streamer to stop at
    the next token rather than letting generation run to ``max_new_tokens``.
    :meth:`release_when_idle` lets the ``CapabilityRunner`` hold the model slot
    until native inference has actually stopped, so a cancelled request never
    frees capacity that is still in use.
    """

    def __init__(self, streamer: YieldingTextStreamer,
                 think_filter: Optional[StreamThinkFilter] = None, call=None) -> None:
        self._streamer = streamer
        self._tokens = iter(streamer)
        self._filter = think_filter
        self._call = call
        self._error: list = []
        self._lock = threading.Lock()
        self._done = False
        self._on_idle: list = []
        self._thread: Optional[threading.Thread] = None

    def start(self, target: Callable[[], None]) -> None:
        self._thread = threading.Thread(target=self._run, args=(target,), daemon=True)
        self._thread.start()

    def _run(self, target) -> None:
        status, failure = "ok", None
        try:
            target()
        except Exception as exc:  # noqa: BLE001 - re-raised in the consumer
            logger.error("VLM text_gen streaming failed: %s", exc)
            self._error.append(exc)
            status, failure = "failed", exc
        finally:
            self._streamer.end()
            with self._lock:
                self._done = True
                callbacks, self._on_idle = self._on_idle, []
            if self._call is not None:
                self._call.finish(status, failure)
            for callback in callbacks:
                callback()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        while True:
            try:
                token = next(self._tokens)
            except StopIteration:
                # The runtime ends the streamer itself before generate()
                # returns; wait so finish_info, metrics and errors are final.
                self._thread.join()
                if self._error:
                    raise self._error[0]
                raise
            if self._filter is not None:
                token = self._filter.filter(token)
                if not token:
                    continue
            return token

    def close(self) -> None:
        """Stop native generation if the consumer leaves before the end."""
        with self._lock:
            finished = self._done
        if not finished:
            if self._call is not None:
                self._call.client_cancelled()
            self._streamer.cancel()

    def release_when_idle(self, callback: Callable[[], None]) -> bool:
        """Defer ``callback`` until generation stops; False if it already has."""
        with self._lock:
            if self._done:
                return False
            self._on_idle.append(callback)
            return True


def _finish_reason(result) -> Optional[str]:
    """Runtime finish reason of the first sequence (``STOP``/``LENGTH``/...), if reported."""
    try:
        reasons = getattr(result, "finish_reasons", None)
        name = getattr(reasons[0], "name", None) if reasons else None
    except Exception:  # noqa: BLE001 - older runtimes / fakes
        return None
    return name if name and name != "NONE" else None


def _mean(pair) -> Optional[float]:
    value = getattr(pair, "mean", None)
    if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
        return float(value)
    return None


def _perf_metrics(result) -> dict:
    """Runtime-reported timing for one call; unavailable fields stay absent."""
    out: dict = {}
    perf = getattr(result, "perf_metrics", None)
    if perf is None:
        return out
    for key, getter in (("ttft_ms", "get_ttft"), ("tpot_ms", "get_tpot")):
        try:
            value = _mean(getattr(perf, getter)())
        except Exception:  # noqa: BLE001 - partial runtime builds
            value = None
        if value is not None:
            out[key] = round(value, 3)
    for key, getter in (("input_tokens", "get_num_input_tokens"),
                        ("output_tokens", "get_num_generated_tokens")):
        try:
            count = getattr(perf, getter)()
            if isinstance(count, int) and count >= 0:
                out[key] = count
        except Exception:  # noqa: BLE001
            pass
    try:
        duration = _mean(perf.get_generate_duration())
        if duration is not None:
            out["runtime_generate_s"] = round(duration / 1000.0, 4)
    except Exception:  # noqa: BLE001
        pass
    if out.get("tpot_ms"):
        out["decode_tps"] = round(1000.0 / out["tpot_ms"], 3)
    extended = getattr(result, "extended_perf_metrics", None)
    if extended is not None:
        for key, getter in (("draft_tokens", "get_num_draft_tokens"),
                            ("accepted_tokens", "get_num_accepted_tokens")):
            try:
                count = getattr(extended, getter)()
                if isinstance(count, int) and count >= 0:
                    out[key] = count
            except Exception:  # noqa: BLE001
                pass
        if not out.get("draft_tokens"):
            # DFlash counts proposals here and leaves get_num_draft_tokens at 0.
            try:
                processed = extended.get_num_draft_processed_tokens()
                if isinstance(processed, int) and processed > 0:
                    out["draft_tokens"] = processed
            except Exception:  # noqa: BLE001
                pass
        try:
            rate = extended.get_draft_acceptance_rate()
            if isinstance(rate, (int, float)) and math.isfinite(rate):
                out["acceptance_rate"] = round(float(rate), 4)
        except Exception:  # noqa: BLE001
            pass
    return out
