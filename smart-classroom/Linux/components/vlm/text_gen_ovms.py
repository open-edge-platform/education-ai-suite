# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0


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
_RETRYABLE_STATUS_CODES = {429, 503}


def _map_ovms_error(exc: httpx.HTTPError, context: str) -> Exception:
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
        self._last_usage: Optional[dict] = None
        self._load_config()
        self._client = httpx.Client(timeout=self._timeout_s, trust_env=False)

    @property
    def last_usage(self) -> Optional[dict]:
        return self._last_usage

    @property
    def device(self) -> Optional[str]:
        return self._device

    @property
    def model_name(self) -> Optional[str]:
        return self._model_name

    # ------------------------------------------------------------------
    # Readiness / health (Phase 4 task 17)
    # ------------------------------------------------------------------
    def check_ready(self) -> dict:
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
        if stream:
            # Streamed replies carry no token counts unless asked for; they
            # arrive in a final chunk whose "choices" list is empty.
            payload["stream_options"] = {"include_usage": True}
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
        import queue

        chunks: "queue.Queue" = queue.Queue()
        _SENTINEL = object()
        error: list[Exception] = []

        def run_request() -> None:
            self._last_usage = None
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
                            usage = event.get("usage")
                            if isinstance(usage, dict) and usage.get("completion_tokens") is not None:
                                self._last_usage = usage
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
