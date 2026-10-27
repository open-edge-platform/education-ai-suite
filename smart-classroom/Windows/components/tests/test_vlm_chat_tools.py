# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""``/v1/chat/completions``: legacy chat unchanged, tool calling per the OpenAI contract."""

import json

import pytest

pytest.importorskip("openvino")
pytest.importorskip("PIL")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api import vlm_chat  # noqa: E402
from components.vlm.text_gen_profiles import UnsupportedRequestError  # noqa: E402

TOOLS = [{"type": "function", "function": {
    "name": "get_weather",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]
CALL = '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call>'


class FakeHandler:
    def __init__(self, output="ok", supports_tools=True, error=None, truncated=False,
                 reasoning_open=False, prefill=""):
        self.output = output
        self.supports_tools = supports_tools
        self.error = error
        self.truncated = truncated
        self.reasoning_open = reasoning_open
        self.prefill = prefill
        self.calls = []

    def generate(self, prompt=None, **kwargs):
        from utils.processing_stats import current_stage

        kwargs["_stage"] = current_stage()[1]
        self.calls.append((prompt, kwargs))
        if self.error:
            raise self.error
        info = kwargs.get("finish_info")
        if info is not None:
            info.update(reasoning_open=self.reasoning_open, prefill=self.prefill,
                        truncated=self.truncated, input_tokens=11, output_tokens=7)
        if kwargs.get("stream"):
            text = self.output
            return iter([text[i:i + 4] for i in range(0, len(text), 4)])
        return self.output


@pytest.fixture
def client_for(monkeypatch):
    def make(handler):
        monkeypatch.setattr(vlm_chat.ModelManager, "instance",
                            classmethod(lambda cls: type("M", (), {"text_gen": lambda self: handler})()))
        monkeypatch.setattr(vlm_chat, "_model_name", lambda requested: "Qwen/Qwen3.6-35B-A3B")
        app = FastAPI()
        app.include_router(vlm_chat.router)
        return TestClient(app)
    return make


def _sse(response):
    events = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            body = line[len("data:"):].strip()
            events.append(body if body == "[DONE]" else json.loads(body))
    return events


# --- legacy path is unchanged -------------------------------------------------
def test_plain_chat_still_sends_only_the_last_user_turn(client_for):
    handler = FakeHandler("hello")
    client = client_for(handler)
    r = client.post("/v1/chat/completions", json={"messages": [
        {"role": "system", "content": "sys"}, {"role": "user", "content": "first"},
        {"role": "assistant", "content": "a"}, {"role": "user", "content": "last"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0] == {"index": 0, "message": {"role": "assistant", "content": "hello"},
                                  "finish_reason": "stop"}
    prompt, kwargs = handler.calls[0]
    assert prompt == "last" and "tools" not in kwargs and "messages" not in kwargs


def test_plain_stream_shape_is_unchanged(client_for):
    client = client_for(FakeHandler("hello world"))
    with client.stream("POST", "/v1/chat/completions",
                       json={"stream": True, "messages": [{"role": "user", "content": "x"}]}) as r:
        events = _sse(r)
    assert events[0]["choices"][0]["delta"] == {"role": "assistant"}
    assert "".join(e["choices"][0]["delta"].get("content", "") for e in events[1:-2]) == "hello world"
    assert events[-2]["choices"][0]["finish_reason"] == "stop" and events[-1] == "[DONE]"


def test_plain_chat_reports_runtime_usage(client_for):
    r = client_for(FakeHandler("hello")).post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "x"}]})
    assert r.json()["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}


@pytest.mark.parametrize("stream", [False, True])
def test_plain_chat_cut_at_max_tokens_finishes_with_length(client_for, stream):
    client = client_for(FakeHandler("hello", truncated=True))
    payload = {"stream": stream, "messages": [{"role": "user", "content": "x"}]}
    if not stream:
        assert client.post("/v1/chat/completions", json=payload).json()[
            "choices"][0]["finish_reason"] == "length"
        return
    with client.stream("POST", "/v1/chat/completions", json=payload) as r:
        events = _sse(r)
    assert events[-2]["choices"][0]["finish_reason"] == "length"


@pytest.mark.parametrize("tools", [None, TOOLS])
def test_stream_include_usage_ends_with_a_usage_chunk(client_for, tools):
    payload = {"stream": True, "stream_options": {"include_usage": True},
               "messages": [{"role": "user", "content": "x"}]}
    if tools:
        payload["tools"] = tools
    with client_for(FakeHandler("hello")).stream("POST", "/v1/chat/completions",
                                                  json=payload) as r:
        events = _sse(r)
    assert events[-1] == "[DONE]"
    assert events[-2]["choices"] == [] and events[-2]["usage"] == {
        "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert events[-3]["choices"][0]["finish_reason"] == "stop"


@pytest.mark.parametrize("tools", [None, TOOLS])
def test_request_sampling_is_forwarded_only_when_set(client_for, tools):
    handler = FakeHandler("ok")
    client = client_for(handler)
    payload = {"messages": [{"role": "user", "content": "x"}],
               "presence_penalty": 1.5, "repetition_penalty": 1.05, "top_p": 0.8, "top_k": 20}
    if tools:
        payload["tools"] = tools
    client.post("/v1/chat/completions", json=payload)
    client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "x"}]})
    assert handler.calls[0][1]["sampling"] == {
        "presence_penalty": 1.5, "repetition_penalty": 1.05, "top_p": 0.8, "top_k": 20}
    assert handler.calls[1][1]["sampling"] is None


@pytest.mark.parametrize("field, value", [
    ("presence_penalty", 2.5), ("frequency_penalty", -3), ("repetition_penalty", 0),
    ("top_p", 0), ("top_p", 1.5), ("top_k", 0),
])
def test_out_of_range_sampling_is_a_400_before_generation(client_for, field, value):
    handler = FakeHandler("ok")
    r = client_for(handler).post("/v1/chat/completions", json={
        field: value, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 400 and handler.calls == []


@pytest.mark.parametrize("url", ["C:/Users/x/photo.png", "https://example.com/x.png"])
def test_plain_chat_accepts_only_inline_images(client_for, url):
    handler = FakeHandler("ok")
    r = client_for(handler).post("/v1/chat/completions", json={"messages": [{
        "role": "user", "content": [{"type": "image_url", "image_url": {"url": url}},
                                    {"type": "text", "text": "describe"}]}]})
    assert r.status_code == 400 and "data:image/" in r.json()["error"]
    assert handler.calls == []


def test_request_the_pipeline_cannot_honor_is_a_400(client_for):
    client = client_for(FakeHandler(error=UnsupportedRequestError("greedy decoding only")))
    r = client.post("/v1/chat/completions", json={
        "temperature": 0.7, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 400 and "greedy" in r.json()["error"]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("header, stage", [
    ({"X-SC-Stage": "qa"}, "qa"),
    ({"X-SC-Stage": "../etc"}, "chat_api"),
    ({}, "chat_api"),
])
def test_calls_are_attributed_to_the_caller_stage(client_for, stream, header, stage):
    handler = FakeHandler("hello")
    client_for(handler).post("/v1/chat/completions", headers=header, json={
        "stream": stream, "messages": [{"role": "user", "content": "x"}]})
    assert handler.calls[0][1]["_stage"] == stage


# --- tool calling -----------------------------------------------------------------
def test_non_streaming_tool_call(client_for):
    handler = FakeHandler(CALL)
    client = client_for(handler)
    r = client.post("/v1/chat/completions", json={
        "tools": TOOLS, "messages": [{"role": "system", "content": "s"},
                                     {"role": "user", "content": "Weather in Paris?"}]})
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] is None
    (call,) = choice["message"]["tool_calls"]
    assert call["type"] == "function" and call["id"].startswith("call_")
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}
    assert r.json()["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    _, kwargs = handler.calls[0]
    assert [m["role"] for m in kwargs["messages"]] == ["system", "user"]  # full history
    assert kwargs["tools"][0]["function"]["name"] == "get_weather"


def test_tool_result_round_trip_answers_with_stop(client_for):
    handler = FakeHandler("It is 21 C in Paris.")
    client = client_for(handler)
    r = client.post("/v1/chat/completions", json={"tools": TOOLS, "messages": [
        {"role": "user", "content": "Weather in Paris?"},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_a", "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city": "Paris"}'}}]},
        {"role": "tool", "tool_call_id": "call_a", "content": '{"temp": 21}'}]})
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "stop" and "tool_calls" not in choice["message"]
    history = handler.calls[0][1]["messages"]
    assert history[-1] == {"role": "tool", "content": '{"temp": 21}', "tool_call_id": "call_a",
                           "name": "get_weather"}


def test_streaming_tool_call_is_published_whole(client_for):
    client = client_for(FakeHandler("Sure. " + CALL))
    with client.stream("POST", "/v1/chat/completions",
                       json={"stream": True, "tools": TOOLS,
                             "messages": [{"role": "user", "content": "w?"}]}) as r:
        events = _sse(r)
    deltas = [e["choices"][0]["delta"] for e in events if isinstance(e, dict)]
    calls = [d["tool_calls"] for d in deltas if "tool_calls" in d]
    assert len(calls) == 1 and calls[0][0]["index"] == 0
    assert json.loads(calls[0][0]["function"]["arguments"]) == {"city": "Paris"}
    assert events[-2]["choices"][0]["finish_reason"] == "tool_calls" and events[-1] == "[DONE]"
    assert "<tool_call>" not in "".join(d.get("content", "") for d in deltas)


def test_invalid_generated_call_is_an_error_not_a_success(client_for):
    bad = '<tool_call>\n{"name": "get_weather", "arguments": {}}\n</tool_call>'
    client = client_for(FakeHandler(bad))
    r = client.post("/v1/chat/completions",
                    json={"tools": TOOLS, "messages": [{"role": "user", "content": "w?"}]})
    assert r.status_code == 502
    assert r.json()["error"]["type"] == "tool_call_validation_failed"

    with client.stream("POST", "/v1/chat/completions",
                       json={"stream": True, "tools": TOOLS,
                             "messages": [{"role": "user", "content": "w?"}]}) as r:
        events = _sse(r)
    assert any(isinstance(e, dict) and "error" in e for e in events)
    assert not any(isinstance(e, dict) and "choices" in e
                   and e["choices"][0]["finish_reason"] == "tool_calls" for e in events)
    assert events[-1] == "[DONE]"


@pytest.mark.parametrize("stream", [False, True])
def test_reasoning_is_returned_apart_from_content(client_for, stream):
    handler = FakeHandler("Need the weather.\n</think>\n\n" + CALL, reasoning_open=True)
    payload = {"stream": stream, "tools": TOOLS, "messages": [{"role": "user", "content": "w?"}]}
    if stream:
        with client_for(handler).stream("POST", "/v1/chat/completions", json=payload) as r:
            deltas = [e["choices"][0]["delta"] for e in _sse(r) if isinstance(e, dict)]
        reasoning = "".join(d.get("reasoning_content", "") for d in deltas)
        content = "".join(d.get("content") or "" for d in deltas)
    else:
        message = client_for(handler).post("/v1/chat/completions", json=payload).json()[
            "choices"][0]["message"]
        reasoning, content = message["reasoning_content"], message["content"] or ""
        assert len(message["tool_calls"]) == 1
    assert reasoning.strip() == "Need the weather." and content == ""


@pytest.mark.parametrize("tool_choice, forced", [
    ("required", ""),
    ({"type": "function", "function": {"name": "get_weather"}}, "get_weather"),
])
def test_required_and_named_choices_force_the_call(client_for, tool_choice, forced):
    prefill = '<tool_call>\n{"name": "get_weather", "arguments": '
    handler = FakeHandler('{"city": "Paris"}}\n</tool_call>', prefill=prefill)
    r = client_for(handler).post("/v1/chat/completions", json={
        "tools": TOOLS, "tool_choice": tool_choice, "messages": [{"role": "user", "content": "w?"}]})
    assert r.status_code == 200
    assert handler.calls[0][1]["force_tool_call"] == forced
    (call,) = r.json()["choices"][0]["message"]["tool_calls"]
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris"}
    handler = FakeHandler("ok")
    client_for(handler).post("/v1/chat/completions", json={
        "tools": TOOLS, "messages": [{"role": "user", "content": "w?"}]})
    assert "force_tool_call" not in handler.calls[0][1]  # auto stays the model's choice


def test_required_choice_without_call_fails(client_for):
    client = client_for(FakeHandler("I will not call anything."))
    r = client.post("/v1/chat/completions", json={
        "tools": TOOLS, "tool_choice": "required", "messages": [{"role": "user", "content": "w?"}]})
    assert r.status_code == 502


def test_truncated_tool_turn_reports_length(client_for):
    client = client_for(FakeHandler(CALL[:30], truncated=True))
    r = client.post("/v1/chat/completions",
                    json={"tools": TOOLS, "messages": [{"role": "user", "content": "w?"}]})
    assert r.status_code == 200
    choice = r.json()["choices"][0]
    assert choice["finish_reason"] == "length" and "tool_calls" not in choice["message"]


class _FailingStream:
    """Yields one token, then fails as the runner does on a native error."""

    def __init__(self):
        self.closed = False
        self._sent = False

    def __iter__(self):
        return self

    def __next__(self):
        if not self._sent:
            self._sent = True
            return "partial "
        from model_manager.capability.runner import OomError
        raise OomError("GPU out of memory at C:/models/x")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("tools", [False, True])
def test_a_generation_failure_mid_stream_ends_with_an_error_and_done(client_for, tools):
    stream = _FailingStream()
    handler = FakeHandler()
    handler.generate = lambda prompt=None, **kwargs: (
        kwargs["finish_info"].update(reasoning_open=False, prefill="")
        if "finish_info" in kwargs else None) or stream
    payload = {"stream": True, "messages": [{"role": "user", "content": "w?"}]}
    if tools:
        payload["tools"] = TOOLS
    with client_for(handler).stream("POST", "/v1/chat/completions", json=payload) as r:
        assert r.status_code == 200
        events = _sse(r)
    errors = [e["error"] for e in events if isinstance(e, dict) and "error" in e]
    assert errors == [{"message": "generation failed", "type": "server_error", "code": None}]
    assert events[-1] == "[DONE]" and stream.closed


@pytest.mark.parametrize("field", ["max_tokens", "max_completion_tokens"])
@pytest.mark.parametrize("value", [0, -1])
def test_non_positive_token_limits_are_rejected(client_for, field, value):
    handler = FakeHandler()
    r = client_for(handler).post("/v1/chat/completions", json={
        field: value, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 400 and handler.calls == []


def test_streamed_complete_call_is_withheld_when_the_turn_is_truncated(client_for):
    client = client_for(FakeHandler(CALL + "\nAlso", truncated=True))
    with client.stream("POST", "/v1/chat/completions",
                       json={"stream": True, "tools": TOOLS,
                             "messages": [{"role": "user", "content": "w?"}]}) as r:
        events = _sse(r)
    deltas = [e["choices"][0]["delta"] for e in events if isinstance(e, dict)]
    assert not any("tool_calls" in d for d in deltas)
    assert events[-2]["choices"][0]["finish_reason"] == "length" and events[-1] == "[DONE]"


@pytest.mark.parametrize("payload", [
    {"tools": [{"type": "function", "function": {"name": "bad name"}}],
     "messages": [{"role": "user", "content": "x"}]},
    {"tools": TOOLS, "tool_choice": {"type": "function", "function": "get_weather"},
     "messages": [{"role": "user", "content": "x"}]},
    {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": None,
                  "tool_calls": [{"id": "c", "type": "function", "function": "invalid"}]},
                  {"role": "tool", "tool_call_id": "c", "content": "r"}]},
    {"tools": TOOLS, "tool_choice": {"type": "function", "function": {"name": "nope"}},
     "messages": [{"role": "user", "content": "x"}]},
    {"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": None,
                  "tool_calls": [{"id": "c", "type": "function",
                                  "function": {"name": "f", "arguments": "{}"}}]}]},
])
def test_malformed_tool_requests_are_rejected_before_generation(client_for, payload):
    handler = FakeHandler()
    r = client_for(handler).post("/v1/chat/completions", json=payload)
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"
    assert handler.calls == []


def test_model_without_tool_support_is_rejected(client_for):
    handler = FakeHandler(supports_tools=False)
    r = client_for(handler).post("/v1/chat/completions", json={
        "tools": TOOLS, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 400 and "does not support tool calling" in r.json()["error"]["message"]
    assert handler.calls == []


def test_tool_choice_none_works_without_tool_support(client_for):
    handler = FakeHandler("plain answer", supports_tools=False)
    r = client_for(handler).post("/v1/chat/completions", json={
        "tools": TOOLS, "tool_choice": "none", "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "plain answer"
    assert handler.calls[0][1]["tools"] is None
