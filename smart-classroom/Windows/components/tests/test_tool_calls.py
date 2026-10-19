# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Tool-calling contract: request validation, history, output parsing, streaming."""

import json

import pytest

from components.vlm import tool_calls as tc

WEATHER = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Current weather",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 7},
                "unit": {"type": "string", "enum": ["c", "f"]},
            },
            "required": ["city"],
            "additionalProperties": False,
        },
    },
}
TIME = {"type": "function", "function": {"name": "get_time"}}


def _tools():
    return tc.normalize_tools([WEATHER, TIME])


def _choice(raw=None):
    return tc.resolve_tool_choice(raw, _tools())


# --- request validation -------------------------------------------------------
def test_normalize_tools_defaults_parameters_and_renders_for_template():
    tools = _tools()
    assert [t.name for t in tools] == ["get_weather", "get_time"]
    assert tools[1].parameters == {"type": "object", "properties": {}}
    rendered = tools[0].for_template()
    assert rendered["type"] == "function"
    assert rendered["function"]["description"] == "Current weather"


@pytest.mark.parametrize("bad, message", [
    ("nope", "must be a list"),
    ([{"type": "retrieval"}], 'only type "function"'),
    ([{"type": "function", "function": {"name": "bad name"}}], "must match"),
    ([WEATHER, WEATHER], "duplicate function name"),
    ([{"type": "function", "function": {"name": "f", "parameters": {"type": "string"}}}],
     'type "object"'),
    ([{"type": "function", "function": {"name": "f", "parameters": {
        "type": "object", "properties": {"x": {"$ref": "#/$defs/X"}}}}}], "unsupported JSON Schema"),
    ([{"type": "function", "function": {"name": "f", "parameters": {
        "type": "object", "properties": {"x": {"type": "string", "pattern": "a+"}}}}}],
     "unsupported JSON Schema"),
    ([{"type": "function", "function": {"name": "f", "extra": 1}}], "unsupported field"),
])
def test_invalid_tools_are_rejected(bad, message):
    with pytest.raises(tc.ToolRequestError, match=message):
        tc.normalize_tools(bad)


def test_tool_choice_defaults_and_validation():
    assert _choice().mode == "auto"
    assert tc.resolve_tool_choice(None, []).mode == "none"
    assert _choice("required").requires_call
    named = _choice({"type": "function", "function": {"name": "get_time"}})
    assert named.mode == "named" and named.name == "get_time"
    assert [t.name for t in tc.offered_tools(_tools(), named)] == ["get_time"]
    assert tc.offered_tools(_tools(), _choice("none")) == []
    with pytest.raises(tc.ToolRequestError, match="not in tools"):
        _choice({"type": "function", "function": {"name": "absent"}})
    with pytest.raises(tc.ToolRequestError, match="requires tools"):
        tc.resolve_tool_choice("required", [])
    with pytest.raises(tc.ToolRequestError):
        _choice("sometimes")


# --- JSON Schema subset --------------------------------------------------------
def test_schema_validation_reports_paths_not_values():
    schema = _tools()[0].parameters
    assert tc.validate({"city": "Paris", "days": 3}, schema) == []
    errors = tc.validate({"days": 9, "unit": "k", "secret": "hunter2"}, schema)
    joined = " ".join(errors)
    assert "city: required" in joined and "above maximum" in joined
    assert "not one of the allowed" in joined and "secret: property not allowed" in joined
    assert "hunter2" not in joined


def test_schema_types_any_of_and_nullable():
    schema = {"type": "object", "properties": {
        "n": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "tags": {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
        "flag": {"type": "boolean", "nullable": True},
    }}
    tc.check_schema(schema)
    assert tc.validate({"n": None, "tags": ["a"], "flag": None}, schema) == []
    assert tc.validate({"n": True}, schema)  # bool is not an integer
    assert tc.validate({"tags": ["a", "a"]}, schema)
    assert tc.validate({"tags": [1]}, schema)


# --- history --------------------------------------------------------------------
def _call(call_id="call_1", name="get_weather", args='{"city": "Paris"}'):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def test_history_keeps_order_roles_and_associates_results():
    messages = [
        {"role": "developer", "content": "Be brief."},
        {"role": "user", "content": [{"type": "text", "text": "Weather?"}]},
        {"role": "assistant", "content": None, "tool_calls": [_call()]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 21}'},
    ]
    history, images = tc.normalize_history(messages)
    assert [m["role"] for m in history] == ["system", "user", "assistant", "tool"]
    assert history[2]["content"] == ""
    assert history[2]["tool_calls"][0]["function"]["arguments"] == {"city": "Paris"}
    assert history[3]["name"] == "get_weather" and history[3]["tool_call_id"] == "call_1"
    assert images == []


def test_history_collects_images_with_per_message_tags():
    messages = [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            {"type": "text", "text": "What is this?"}]},
        {"role": "assistant", "content": "A cat."},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
            {"type": "text", "text": "And this?"}]},
    ]
    history, images = tc.normalize_history(messages)
    assert len(images) == 2
    assert history[0]["content"].startswith("<ov_genai_image_0>")
    assert history[2]["content"].startswith("<ov_genai_image_1>")


@pytest.mark.parametrize("messages, message", [
    ([], "must not be empty"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [_call()]}], "have no tool result"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [_call()]}, {"role": "user", "content": "again"}], "have no tool result"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [_call()]}, {"role": "tool", "tool_call_id": "call_9", "content": "x"}],
     "does not match"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [_call()]}, {"role": "tool", "tool_call_id": "call_1", "content": "x"},
      {"role": "tool", "tool_call_id": "call_1", "content": "y"}], "duplicates an earlier result"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [_call(), _call()]}], "duplicates an earlier call id"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [_call(args="not json")]}], "JSON-encoded object"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": None,
      "tool_calls": [{"id": "call_a", "type": "function", "function": "invalid"}]}],
     "function must be an object"),
    ([{"role": "user", "content": "hi"}, {"role": "assistant", "content": "done"}],
     "last message"),
    ([{"role": "narrator", "content": "hi"}], "not supported"),
    ([{"role": "system", "content": [{"type": "image_url", "image_url": {"url": "u"}}]}],
     "only supported in user"),
    ([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "C:/x.png"}}]}],
     "data:image/"),
    ([{"role": "user", "content": [{"type": "image_url",
                                    "image_url": {"url": "https://example.com/x.png"}}]}],
     "data:image/"),
])
def test_invalid_history_is_rejected(messages, message):
    with pytest.raises(tc.ToolRequestError, match=message):
        tc.normalize_history(messages)


def test_history_passes_returned_reasoning_back_to_the_template():
    messages = [{"role": "user", "content": "w?"},
                {"role": "assistant", "content": None, "tool_calls": [_call()],
                 "reasoning_content": "Need the weather."},
                {"role": "tool", "tool_call_id": "call_1", "content": "21"}]
    history, _ = tc.normalize_history(messages)
    assert history[1]["reasoning_content"] == "Need the weather."


def test_is_tool_conversation_leaves_plain_chat_on_the_legacy_path():
    plain = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    assert not tc.is_tool_conversation(None, None, plain)
    assert tc.is_tool_conversation([WEATHER], None, plain)
    assert tc.is_tool_conversation(None, "none", plain)
    assert tc.is_tool_conversation(None, None, plain + [{"role": "tool", "tool_call_id": "x"}])


# --- output parsing -------------------------------------------------------------
HERMES = '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris", "days": 2}}\n</tool_call>'
XML = ("<tool_call>\n<function=get_weather>\n<parameter=city>\nParis\n</parameter>\n"
       "<parameter=days>\n2\n</parameter>\n</function>\n</tool_call>")


@pytest.mark.parametrize("text", [HERMES, XML])
def test_parse_completion_normalizes_both_qwen_syntaxes(text):
    turn = tc.parse_completion("Let me check.\n" + text, _tools(), _choice())
    assert turn.finish_reason == "tool_calls"
    assert turn.content.strip() == "Let me check."
    call = turn.tool_calls[0]
    assert call["id"].startswith("call_") and call["type"] == "function"
    assert call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "Paris", "days": 2}


def test_plain_text_turn_finishes_with_stop():
    turn = tc.parse_completion("It is sunny.", _tools(), _choice())
    assert turn.finish_reason == "stop" and turn.tool_calls == []


def test_multiple_calls_get_distinct_ids_and_parallel_false_keeps_one():
    text = HERMES + "\n" + '<tool_call>\n{"name": "get_time", "arguments": {}}\n</tool_call>'
    turn = tc.parse_completion(text, _tools(), _choice())
    ids = [c["id"] for c in turn.tool_calls]
    assert len(ids) == 2 and len(set(ids)) == 2
    single = tc.parse_completion(text, _tools(), _choice(), parallel=False)
    assert [c["function"]["name"] for c in single.tool_calls] == ["get_weather"]


@pytest.mark.parametrize("text, message", [
    ('<tool_call>\n{"name": "get_weather", "arguments": {"days": 2}}\n</tool_call>', "invalid arguments"),
    ('<tool_call>\n{"name": "launch", "arguments": {}}\n</tool_call>', "not offered"),
    ("<tool_call>\n{not json}\n</tool_call>", "not valid JSON"),
    ("<tool_call>\nsomething else\n</tool_call>", "unrecognized"),
    ('<tool_call>\n{"name": "get_weather", "arguments": {"city": "P"', "unterminated"),
])
def test_invalid_generated_calls_are_errors_not_successes(text, message):
    with pytest.raises(tc.ToolOutputError, match=message):
        tc.parse_completion(text, _tools(), _choice())


def test_truncated_call_reports_length_without_calls():
    text = HERMES + '\n<tool_call>\n{"name": "get_time", "argu'
    turn = tc.parse_completion(text, _tools(), _choice(), truncated=True)
    assert turn.finish_reason == "length" and turn.tool_calls == []


def test_truncation_takes_precedence_over_complete_calls():
    # A complete call, then text cut off by the token limit.
    text = HERMES + "\nAnd then I will also"
    turn = tc.parse_completion(text, _tools(), _choice(), truncated=True)
    assert turn.finish_reason == "length" and turn.tool_calls == []
    parser = tc.ToolStreamParser(_tools(), _choice())
    parser.feed(text)
    parser.finish(True)
    assert parser.finish_reason == "length"


def test_required_and_named_choices_demand_a_matching_call():
    with pytest.raises(tc.ToolOutputError, match="required tool call"):
        tc.parse_completion("No.", _tools(), _choice("required"))
    named = _choice({"type": "function", "function": {"name": "get_time"}})
    with pytest.raises(tc.ToolOutputError, match="not offered"):
        tc.parse_completion(HERMES, _tools(), named)


def test_choice_none_never_parses_calls():
    turn = tc.parse_completion(HERMES, _tools(), _choice("none"))
    assert turn.tool_calls == [] and "<tool_call>" in turn.content


def test_calls_inside_reasoning_are_ignored():
    text = "<think>maybe <tool_call>{\"name\": \"get_time\"}</tool_call></think>" + HERMES
    turn = tc.parse_completion(text, _tools(), _choice())
    assert [c["function"]["name"] for c in turn.tool_calls] == ["get_weather"]
    opened = "thinking about <tool_call> stuff</think>\n" + HERMES
    turn = tc.parse_completion(opened, _tools(), _choice(), reasoning_open=True)
    assert len(turn.tool_calls) == 1 and turn.content == ""
    assert turn.reasoning == "thinking about <tool_call> stuff"


def test_parallel_false_ignores_extra_calls_even_if_invalid():
    text = HERMES + '\n<tool_call>\n{"name": "launch", "arguments": {}}\n</tool_call>'
    turn = tc.parse_completion(text, _tools(), _choice(), parallel=False)
    assert [c["function"]["name"] for c in turn.tool_calls] == ["get_weather"]


@pytest.mark.parametrize("prefill, output", [
    ('<tool_call>\n{"name": "get_weather", "arguments": ', '{"city": "Paris"}}\n</tool_call>'),
    ("<tool_call>\n<function=get_weather>\n",
     "<parameter=city>\nParis\n</parameter>\n</function>\n</tool_call>"),
])
def test_forced_call_output_continues_the_prefill(prefill, output):
    named = _choice({"type": "function", "function": {"name": "get_weather"}})
    turn = tc.parse_completion(output, _tools(), named, prefill=prefill)
    assert turn.finish_reason == "tool_calls" and turn.content == ""
    assert json.loads(turn.tool_calls[0]["function"]["arguments"]) == {"city": "Paris"}


# --- streaming ------------------------------------------------------------------
def _stream(text, chunk, **kwargs):
    parser = tc.ToolStreamParser(_tools(), _choice(), **kwargs)
    events = []
    for i in range(0, len(text), chunk):
        events += parser.feed(text[i:i + chunk])
    events += parser.finish(False)
    return events, parser.finish_reason


@pytest.mark.parametrize("chunk", [1, 3, 7, 1000])
def test_stream_buffers_calls_until_complete_regardless_of_chunking(chunk):
    events, reason = _stream("Checking <tool" + "s now. " + HERMES, chunk)
    content = "".join(v for k, v in events if k == "content")
    calls = [v for k, v in events if k == "call"]
    assert content.strip() == "Checking <tools now."
    assert len(calls) == 1 and reason == "tool_calls"
    # The call event is emitted whole: name and complete JSON arguments.
    assert json.loads(calls[0]["function"]["arguments"])["city"] == "Paris"


@pytest.mark.parametrize("chunk", [1, 4, 1000])
def test_reasoning_is_separate_and_surrounding_whitespace_is_not_content(chunk):
    text = "Plan the call.\n</think>\n\nLet me check.\n\n" + HERMES + "\n"
    events, reason = _stream(text, chunk, reasoning_open=True)
    assert "".join(v for k, v in events if k == "reasoning").strip() == "Plan the call."
    assert "".join(v for k, v in events if k == "content") == "Let me check."
    assert reason == "tool_calls"
    answer = tc.parse_completion("<think>\nok\n</think>\n\nIt is\n\n21 C.\n", _tools(), _choice())
    assert (answer.content, answer.reasoning) == ("It is\n\n21 C.", "ok")


def test_stream_never_emits_partial_call_text():
    parser = tc.ToolStreamParser(_tools(), _choice())
    events = parser.feed('<tool_call>\n{"name": "get_weather", "argu')
    assert events == []


def test_stream_invalid_call_raises_mid_stream():
    parser = tc.ToolStreamParser(_tools(), _choice())
    with pytest.raises(tc.ToolOutputError):
        parser.feed('<tool_call>{"name": "get_weather", "arguments": {}}</tool_call>')


def test_stream_finish_on_truncation_and_unterminated():
    parser = tc.ToolStreamParser(_tools(), _choice())
    parser.feed('<tool_call>{"name": "get_wea')
    assert parser.finish(True) == [] and parser.finish_reason == "length"
    parser = tc.ToolStreamParser(_tools(), _choice())
    parser.feed('<tool_call>{"name": "get_wea')
    with pytest.raises(tc.ToolOutputError, match="unterminated"):
        parser.finish(False)
