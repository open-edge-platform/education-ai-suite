# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``components/vlm/text_gen_ovms.py::TextGenOVMS`` (Phase 5
task 19 of docs/ovms-integration-hld.md): streaming + non-streaming request/
response mapping and OVMS/network error-mapping, all against a mocked HTTP
transport -- no real OVMS/network access.
"""

import json

import httpx
import pytest

from components.vlm.text_gen_ovms import TextGenOVMS, _map_ovms_error
from model_manager.capability.runner import OomError


def _make_backend(monkeypatch, transport: httpx.MockTransport) -> TextGenOVMS:
    """Build a TextGenOVMS without touching utils.config_loader/real config,
    then swap in a mocked transport for its HTTP client."""
    monkeypatch.setattr(TextGenOVMS, "_load_config", lambda self: None)
    backend = TextGenOVMS()
    backend._endpoint = "http://ovms.test:9000"
    backend._api_path = "/v3/chat/completions"
    backend._model_name = "Qwen/Qwen3-VL-8B-Instruct"
    backend._auth_token = None
    backend._timeout_s = 5.0
    backend._max_new_tokens = 128
    backend._client = httpx.Client(transport=transport, timeout=5.0)
    return backend


# --------------------------------------------------------------------------
# Non-streaming request/response mapping
# --------------------------------------------------------------------------

def test_generate_once_maps_messages_to_openai_payload_and_returns_content(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello world"}}]},
        )

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    result = backend.generate(prompt="hi", stream=False)

    assert result == "hello world"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["body"]["stream"] is False
    assert captured["body"]["model"] == "Qwen/Qwen3-VL-8B-Instruct"


def test_generate_once_with_images_builds_multipart_content(monkeypatch):
    captured = {}

    class _FakeTensor:
        def __init__(self):
            import numpy as np
            self.data = np.zeros((1, 2, 2, 3), dtype="uint8")

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    backend.generate(
        messages=[{"role": "user", "content": "describe this"}],
        images=[_FakeTensor()],
        stream=False,
    )

    parts = captured["body"]["messages"][-1]["content"]
    assert parts[0] == {"type": "text", "text": "describe this"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_generate_rejects_both_prompt_and_messages(monkeypatch):
    backend = _make_backend(monkeypatch, httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(ValueError):
        backend.generate(prompt="hi", messages=[{"role": "user", "content": "hi"}])


# --------------------------------------------------------------------------
# Streaming (SSE) response parsing
# --------------------------------------------------------------------------

def test_generate_stream_parses_sse_chunks_and_stops_at_done(monkeypatch):
    sse_body = (
        'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "lo"}}]}\n\n'
        'data: [DONE]\n\n'
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body)

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    chunks = list(backend.generate(prompt="hi", stream=True))

    assert chunks == ["Hel", "lo"]


def test_generate_stream_ignores_malformed_sse_lines(monkeypatch):
    sse_body = (
        "data: not-json\n\n"
        'data: {"choices": [{"delta": {"content": "ok"}}]}\n\n'
        "data: [DONE]\n\n"
    ).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body)

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    chunks = list(backend.generate(prompt="hi", stream=True))

    assert chunks == ["ok"]


# --------------------------------------------------------------------------
# Error mapping (Phase 4 task 15, re-verified here per task 19)
# --------------------------------------------------------------------------

def test_timeout_maps_to_oom_error():
    exc = httpx.ConnectTimeout("timed out")
    mapped = _map_ovms_error(exc, "OVMS request")
    assert isinstance(mapped, OomError)


def test_connect_error_maps_to_oom_error():
    exc = httpx.ConnectError("connection refused")
    mapped = _map_ovms_error(exc, "OVMS request")
    assert isinstance(mapped, OomError)


@pytest.mark.parametrize("status", [429, 503])
def test_overloaded_status_maps_to_oom_error(status):
    request = httpx.Request("POST", "http://ovms.test:9000/v3/chat/completions")
    response = httpx.Response(status, request=request)
    exc = httpx.HTTPStatusError("overloaded", request=request, response=response)
    mapped = _map_ovms_error(exc, "OVMS request")
    assert isinstance(mapped, OomError)


def test_other_5xx_status_maps_to_runtime_error():
    request = httpx.Request("POST", "http://ovms.test:9000/v3/chat/completions")
    response = httpx.Response(500, request=request)
    exc = httpx.HTTPStatusError("server error", request=request, response=response)
    mapped = _map_ovms_error(exc, "OVMS request")
    assert isinstance(mapped, RuntimeError)
    assert not isinstance(mapped, OomError)


def test_generate_once_propagates_mapped_error_on_http_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    with pytest.raises(OomError):
        backend.generate(prompt="hi", stream=False)


def test_generate_stream_propagates_mapped_error_on_http_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        list(backend.generate(prompt="hi", stream=True))


# --------------------------------------------------------------------------
# Readiness (Phase 4 task 17)
# --------------------------------------------------------------------------

def test_check_ready_reports_unreachable_on_connect_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    status = backend.check_ready()

    assert status["reachable"] is False
    assert status["ready"] is False


def test_check_ready_reports_ready_when_ovms_responds_200(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/health/ready":
            return httpx.Response(200)
        return httpx.Response(200, json={})

    backend = _make_backend(monkeypatch, httpx.MockTransport(handler))
    status = backend.check_ready()

    assert status["reachable"] is True
    assert status["ready"] is True
