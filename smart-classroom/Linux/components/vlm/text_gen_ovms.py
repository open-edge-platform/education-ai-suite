# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""``text_gen`` backend that talks to an OVMS-served OpenAI-compatible VLM
endpoint over HTTP instead of loading ``ov_genai.VLMPipeline`` in-process.

Implements the same ``TextGen`` protocol as ``components/vlm/text_gen_vlm.py``
(``VLMTextGen``) -- ``generate(prompt|messages, *, images, stream,
max_new_tokens, temperature, json_schema)`` returning either an
``Iterator[str]`` of decoded text chunks (streaming) or a ``str`` (full
response) -- so ``TextGenHandler``/``CapabilityRunner`` and everything above
them (``api/vlm_chat.py``) are completely backend-agnostic; see
``docs/ovms-integration-hld.md`` §3 key design point 4.

Note on sync vs async: ``CapabilityRunner.submit`` (``model_manager/capability/
runner.py``) calls ``self._fn(*args, **kwargs)`` directly on the caller's
thread -- it is not an event loop and never awaits a coroutine. ``VLMTextGen.
generate`` is therefore a *blocking* call, and this class must match that
contract exactly to drop in as a replacement. We use ``httpx.Client`` (sync),
not ``httpx.AsyncClient`` -- the ``ata_ui_server.py`` reference is for the
request/response *shape* (OpenAI-compatible JSON over HTTP, SSE for
streaming), not for async vs sync; this module's blocking streaming iterator
mirrors ``VLMTextGen._generate_stream``'s one (runs the HTTP call on a worker
thread, yields decoded tokens to the consumer).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import threading
from typing import Iterator, Optional, Union

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_MAX_NEW_TOKENS = 5120
_DEFAULT_TIMEOUT_S = 120.0
_DEFAULT_API_PATH = "/v3/chat/completions"

# HTTP statuses OVMS/an upstream proxy returns when it is temporarily unable
# to accept more work (its own queue/batch is full, or it is mid-restart) --
# raised as OomError directly (same 503 + Retry-After semantics main.py
# already gives real memory-pressure errors) rather than a generic
# RuntimeError, since CapabilityRunner only maps (RuntimeError, MemoryError)
# -> OomError and would otherwise lose this distinction in the log message.
_RETRYABLE_STATUS_CODES = {429, 503}


def _map_ovms_error(exc: httpx.HTTPError, context: str) -> Exception:
    """Classify an OVMS HTTP failure into an exception ``CapabilityRunner``
    (``model_manager/capability/runner.py``) already knows how to handle,
    so ``main.py``'s existing ``OomError``/``QueueFullError`` exception
    handlers need no changes (Phase 4 task 15):

    - timeout (connect/read/write/pool)      -> OomError ("ovms_timeout")
    - connection refused / DNS / network     -> OomError ("ovms_unreachable")
    - 429/503 (server temporarily overloaded) -> OomError ("ovms_overloaded")
    - any other HTTP status (4xx/5xx)        -> RuntimeError, which
      ``CapabilityRunner.submit``/``_wrap_stream`` still catches and
      re-raises as ``OomError`` -- so every path here ends up 503'd via the
      same existing handler, just with a more useful logged reason.
    """
    # Deferred import: ``model_manager`` package __init__ pulls in
    # ``ModelManager`` -> ``TextGenHandler`` -> (lazily) this module, so a
    # module-level import here would be circular; ``text_gen_handle.py``
    # defers the same import for the same reason.
    try:
        from model_manager.capability.runner import OomError
    except ImportError:
        from model_manager.capability import OomError

    if isinstance(exc, httpx.TimeoutException):
        return OomError(f"{context} timed out: {exc}")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in _RETRYABLE_STATUS_CODES:
            return OomError(f"{context} rejected by OVMS (HTTP {status}, overloaded): {exc}")
        return RuntimeError(f"{context} failed (HTTP {status}): {exc}")
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return OomError(f"{context} could not reach OVMS: {exc}")
    return RuntimeError(f"{context} failed: {exc}")


def _tensor_to_data_url(tensor) -> str:
    """Re-encode an already-decoded ``ov.Tensor`` frame (HWC uint8) as a PNG
    data URL for OVMS's OpenAI-compatible ``image_url`` content part.

    The ``images`` argument to ``TextGen.generate`` is a list of frames the
    *caller* already decoded from base64/file sources (see
    ``components/vlm/vlm_openvino_serving/utils/utils.py::load_images``) for
    the in-process ``VLMPipeline``, which accepts raw tensors directly. OVMS's
    HTTP API has no equivalent -- it only accepts images embedded in the chat
    ``messages`` as base64 data URLs -- so this is the unavoidable round trip
    to keep the ``TextGen`` protocol (and thus ``images: list[ov.Tensor]``)
    unchanged across both backends.
    """
    from PIL import Image

    array = tensor.data if hasattr(tensor, "data") else tensor
    image = Image.fromarray(array.squeeze())
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class TextGenOVMS:
    """``TextGen`` implementation backed by an OVMS OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        self._endpoint: str = "http://127.0.0.1:9000"
        self._api_path: str = _DEFAULT_API_PATH
        self._model_name: Optional[str] = None
        self._auth_token: Optional[str] = None
        self._timeout_s: float = _DEFAULT_TIMEOUT_S
        self._max_new_tokens: int = _DEFAULT_MAX_NEW_TOKENS
        self._device: Optional[str] = None
        self._load_config()
        self._client = httpx.Client(timeout=self._timeout_s, trust_env=False)

    @property
    def device(self) -> Optional[str]:
        # Reported for ModelManager.health()/memory_stats() parity with
        # VLMTextGen; the model actually runs on whatever device OVMS loaded
        # it with (config.yaml models.text_gen.device), not in this process.
        return self._device

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    # ------------------------------------------------------------------
    # Readiness / health (Phase 4 task 17)
    # ------------------------------------------------------------------
    def check_ready(self) -> dict:
        """Query OVMS's own readiness/model-state endpoints (no local model
        load happens in this process -- OVMS owns that). Returns::

            {"reachable": bool, "ready": bool, "model_state": str|None, "detail": str|None}

        ``reachable`` is False only on a network-level failure (OVMS down /
        unreachable); ``ready`` reflects ``/v2/health/ready``'s HTTP status;
        ``model_state`` is the servable's state from ``/v1/config``
        (``"AVAILABLE"`` once fully loaded), when it can be determined.
        """
        try:
            resp = self._client.get(f"{self._endpoint}/v2/health/ready", timeout=5.0)
            ready = resp.status_code == 200
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "ready": False,
                "model_state": None,
                "detail": str(exc),
            }
        return {
            "reachable": True,
            "ready": ready,
            "model_state": self._fetch_model_state(),
            "detail": None,
        }

    def _fetch_model_state(self) -> Optional[str]:
        """Best-effort lookup of the VLM servable's state via OVMS's
        ``GET /v1/config`` (per-model ``model_version_status``). Returns
        ``None`` if the endpoint is unreachable or the shape is unexpected --
        this is diagnostic information, not required for readiness.
        """
        try:
            resp = self._client.get(f"{self._endpoint}/v1/config", timeout=5.0)
            resp.raise_for_status()
            data = resp.json()
            entry = data.get(self._model_name) if self._model_name else None
            if entry is None and data:
                entry = next(iter(data.values()), None)
            versions = (entry or {}).get("model_version_status") or []
            if versions:
                return versions[0].get("state")
        except Exception:  # noqa: BLE001 - diagnostic only
            return None
        return None

    def wait_ready(self, timeout_s: float = 120.0, poll_interval_s: float = 2.0) -> None:
        """Block until OVMS reports the servable ready, or raise.

        Used by ``TextGenHandler.warmup()`` in place of a blocking in-process
        model load -- OVMS loads/serves the model in its own container, so
        "warming up" here means polling until it's done, not loading
        anything locally.
        """
        import time

        deadline = time.monotonic() + timeout_s
        last: dict = {}
        while True:
            last = self.check_ready()
            if last["ready"] and last["model_state"] in (None, "AVAILABLE"):
                return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"OVMS not ready after {timeout_s}s (endpoint={self._endpoint}): {last}"
                )
            time.sleep(poll_interval_s)

    def _load_config(self) -> None:
        from utils.config_loader import config, resolve_ovms_base_url

        text_gen = getattr(config.models, "text_gen", None)
        if text_gen is None:
            raise ValueError(
                "models.text_gen is not configured; the OVMS text_gen backend cannot start"
            )
        ovms = getattr(text_gen, "ovms", None)
        if ovms is None:
            raise ValueError(
                "models.text_gen.ovms is not configured; required when provider: ovms"
            )

        # servable_name = vlm_name itself (see config.yaml's ovms: block comment) --
        # model-downloader registers it under that name in config_all.json.
        self._model_name = str(getattr(text_gen, "vlm_name"))
        self._device = str(getattr(text_gen, "device", "")).upper() or None
        self._max_new_tokens = int(
            getattr(text_gen, "max_new_tokens", _DEFAULT_MAX_NEW_TOKENS)
        )
        self._endpoint = resolve_ovms_base_url()
        self._api_path = str(getattr(ovms, "api_path", _DEFAULT_API_PATH))
        self._timeout_s = float(getattr(ovms, "timeout_s", _DEFAULT_TIMEOUT_S))
        auth_token = getattr(ovms, "auth_token", None)
        self._auth_token = str(auth_token) if auth_token else None

    def release(self) -> None:
        """Close the HTTP client; mirrors ``VLMTextGen.release()``'s shutdown hook."""
        try:
            self._client.close()
        except Exception:  # noqa: BLE001 - shutdown best-effort
            logger.warning("Failed to close OVMS HTTP client", exc_info=True)

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
    ) -> Union[Iterator[str], str]:
        """Generate from a chat history against the OVMS endpoint.

        Same contract as ``VLMTextGen.generate``: pass ``messages`` or
        ``prompt`` (never both); streaming yields decoded text chunks,
        non-streaming returns the full string. ``enable_thinking`` is not
        applied client-side here (OVMS/the served model handles its own
        chat-template defaults) -- left as a no-op flag for interface parity.
        """
        if (messages is None) == (prompt is None):
            raise ValueError("Provide exactly one of prompt or messages.")
        if messages is None:
            if not prompt.strip():
                raise ValueError("Invalid prompt provided.")
            messages = [{"role": "user", "content": prompt}]
        elif not messages:
            raise ValueError("Invalid messages provided.")

        payload = self._build_payload(
            messages, images, stream, max_new_tokens, temperature, json_schema
        )
        url = f"{self._endpoint}{self._api_path}"
        headers = {"Content-Type": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        if stream:
            return self._generate_stream(url, headers, payload)
        return self._generate_once(url, headers, payload)

    def _build_payload(
        self,
        messages: list,
        images: Optional[list],
        stream: bool,
        max_new_tokens: Optional[int],
        temperature: Optional[float],
        json_schema: Optional[str],
    ) -> dict:
        chat_messages = list(messages)
        if images:
            last = dict(chat_messages[-1])
            text_content = last.get("content", "")
            content_parts = [{"type": "text", "text": text_content}]
            content_parts.extend(
                {"type": "image_url", "image_url": {"url": _tensor_to_data_url(img)}}
                for img in images
            )
            chat_messages[-1] = {**last, "content": content_parts}

        payload: dict = {
            "model": self._model_name,
            "messages": chat_messages,
            "stream": stream,
            "max_tokens": (
                int(max_new_tokens) if max_new_tokens is not None else self._max_new_tokens
            ),
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if json_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": json.loads(json_schema)},
            }
        return payload

    def _generate_once(self, url: str, headers: dict, payload: dict) -> str:
        try:
            resp = self._client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise _map_ovms_error(exc, "OVMS request") from exc
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _generate_stream(self, url: str, headers: dict, payload: dict) -> Iterator[str]:
        """Run the SSE request on a worker thread, yielding text chunks as
        they arrive -- mirrors ``VLMTextGen._generate_stream``'s shape so the
        consumer (``CapabilityRunner``/``api/vlm_chat.py::_sse_stream``) sees
        an identical plain-text token iterator regardless of backend.
        """
        import queue

        chunks: "queue.Queue" = queue.Queue()
        _SENTINEL = object()
        error: list[Exception] = []

        def run_request() -> None:
            try:
                with self._client.stream(
                    "POST", url, headers=headers, json=payload
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:"):].strip()
                        if data == "[DONE]":
                            break
                        try:
                            event = json.loads(data)
                            delta = event["choices"][0].get("delta", {})
                            text = delta.get("content")
                        except (ValueError, KeyError, IndexError):
                            continue
                        if text:
                            chunks.put(text)
            except httpx.HTTPError as exc:
                error.append(_map_ovms_error(exc, "OVMS streaming request"))
            finally:
                chunks.put(_SENTINEL)

        threading.Thread(target=run_request, daemon=True).start()

        def _iterator() -> Iterator[str]:
            while True:
                item = chunks.get()
                if item is _SENTINEL:
                    break
                yield item
            if error:
                raise error[0]

        return _iterator()
