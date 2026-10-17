# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0


from threading import Lock
from typing import Iterator, Optional, Union
import logging

logger = logging.getLogger(__name__)

try:
    from model_manager.capability.state import CapabilityState
except ImportError:
    from model_manager.capability import CapabilityState


_TEXT_GEN_MAX_CONCURRENCY = 1  
_TEXT_GEN_QUEUE_MAX = 8        


def _process_memory_mb() -> Optional[float]:
    """Return process RSS in MB, or None if psutil is unavailable."""
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1024 / 1024, 1)
    except Exception:
        return None


class TextGenHandler:

    def __init__(self) -> None:
        self._runner = None
        self._vlm = None
        self._provider: Optional[str] = "vlm"
        self._device: Optional[str] = None
        self._state = CapabilityState.UNLOADED
        self._max_concurrency: int = _TEXT_GEN_MAX_CONCURRENCY 
        self._lock = Lock()

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
        finish_info: Optional[dict] = None,
    ) -> Union[Iterator[str], str]:
        """Generate from ``messages`` (a chat history) or ``prompt`` (one user
        turn). Templating happens inside the VLM, so callers pass raw text.

        Every call is timed as one model-call record (queue wait separate from
        latency) attributed to the stage open in the caller's context."""
        runner = self._get_runner()
        call = self._model_call(stream)
        extra = {}
        if tools is not None:
            extra["tools"] = tools
        if finish_info is not None:
            extra["finish_info"] = finish_info
        try:
            return runner.submit(
                prompt,
                messages=messages,
                images=images,
                stream=stream,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                enable_thinking=enable_thinking,
                json_schema=json_schema,
                call=call,
                **extra,
            )
        except BaseException as exc:
            # No-op when the VLM already finished the record.
            call.finish("rejected" if type(exc).__name__ == "QueueFullError" else "failed", exc)
            raise

    def _model_call(self, stream: bool):
        from utils.processing_stats import ModelCall

        vlm = self._vlm
        return ModelCall(
            "text_gen",
            model=getattr(vlm, "model_name", None),
            precision=getattr(vlm, "weight_format", None),
            device=self._device,
            decoding=getattr(vlm, "decoding_method", None),
            stream=stream,
        )

    def load(self) -> None:
        self._get_runner()

    @property
    def state(self) -> CapabilityState:
        return self._state

    @property
    def loaded(self) -> bool:
        return self._state == CapabilityState.READY

    @property
    def provider(self) -> Optional[str]:
        return self._provider

    @property
    def device(self) -> Optional[str]:
        return self._device

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @property
    def tokenizer(self):
        self._get_runner()
        return self._vlm.tokenizer

    @property
    def supports_tools(self) -> bool:
        self._get_runner()
        return bool(getattr(self._vlm, "supports_tools", False))

    def serving_status(self) -> dict:
        """Model, tool-call capability and speculative state for /health."""
        status = getattr(self._vlm, "status", None)
        return status() if callable(status) else {}

    def memory_stats(self) -> dict:
        stats: dict = {}
        rss = _process_memory_mb()
        if rss is not None:
            stats["process_rss_mb"] = rss
        return stats

    def shutdown(self) -> None:
        with self._lock:
            if self._state == CapabilityState.READY:
                self._state = CapabilityState.EVICTING
            if self._vlm is not None:
                try:
                    self._vlm.release()
                except Exception:  
                    logger.warning("text_gen VLM release failed", exc_info=True)
            self._runner = None
            self._vlm = None
            self._device = None
            self._state = CapabilityState.UNLOADED


    def _get_runner(self):
        if self._state == CapabilityState.READY:  
            return self._runner
        with self._lock:
            if self._runner is None:
                self._state = CapabilityState.LOADING
                try:
                    vlm = self._build_vlm()
                    max_concurrency, queue_max = self._concurrency_config()
                    self._max_concurrency = max_concurrency
                    try:
                        from model_manager.capability.runner import CapabilityRunner
                    except ImportError:
                        from model_manager.capability import CapabilityRunner
                    self._runner = CapabilityRunner(
                        vlm.generate,
                        max_concurrency=max_concurrency,
                        queue_max=queue_max,
                    )
                    self._state = CapabilityState.READY
                except Exception:
                    self._state = CapabilityState.UNLOADED
                    raise
        return self._runner

    def _concurrency_config(self):
        try:
            from utils.config_loader import config
            text_gen = getattr(config.models, "text_gen", None)
            if text_gen is None:
                return _TEXT_GEN_MAX_CONCURRENCY, _TEXT_GEN_QUEUE_MAX
            return (
                int(getattr(text_gen, "concurrency", _TEXT_GEN_MAX_CONCURRENCY)),
                int(getattr(text_gen, "queue_max", _TEXT_GEN_QUEUE_MAX)),
            )
        except Exception:
            return _TEXT_GEN_MAX_CONCURRENCY, _TEXT_GEN_QUEUE_MAX

    def _build_vlm(self):
        from components.vlm.text_gen_vlm import VLMTextGen

        vlm = VLMTextGen()
        self._vlm = vlm
        self._device = vlm.device
        return vlm
