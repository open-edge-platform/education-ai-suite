# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""OpenAI-compatible function/tool calling for ``/v1/chat/completions``.

The server only *generates* tool calls and *consumes* tool results; it never
executes a function. The flow is: request with ``tools`` -> assistant tool call
-> client-authorized execution -> ``role: "tool"`` result -> answer or next call.

This module is pure (no model, no FastAPI) so every rule is unit-testable:

* :func:`normalize_tools`, :func:`resolve_tool_choice` and
  :func:`normalize_history` validate the request and reject malformed or
  unsupported input with :class:`ToolRequestError` (HTTP 4xx).
* :func:`parse_completion` / :class:`ToolStreamParser` turn the model's
  ``<tool_call>`` syntax -- JSON (Qwen3) or XML ``<function=...>`` (Qwen3.5+)
  -- into OpenAI ``tool_calls``, validating each against the offered schema.
  An invalid or missing required call raises :class:`ToolOutputError`; a call
  cut off by the token limit is reported as ``finish_reason: "length"``.
  Reasoning (``<think>``) is returned apart from the content.

Error messages name schema paths and expectations, never argument values:
tool arguments and results are untrusted and may be sensitive.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

MAX_TOOLS = 128
MAX_SCHEMA_DEPTH = 32
_MAX_ERRORS = 10
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

TOOL_OPEN, TOOL_CLOSE = "<tool_call>", "</tool_call>"
THINK_OPEN, THINK_CLOSE = "<think>", "</think>"
MEDIA_TAG_FMT = "<ov_genai_image_{}>"

_JSON_TYPES = ("string", "number", "integer", "boolean", "object", "array", "null")
_SCHEMA_KEYS = frozenset({
    "type", "properties", "required", "items", "enum", "const", "additionalProperties",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "minItems", "maxItems", "uniqueItems", "anyOf", "oneOf", "allOf", "nullable",
    # Annotations: accepted, not enforced.
    "title", "description", "default", "examples", "format", "$comment", "deprecated",
})


class ToolCallError(Exception):
    """Base class; ``status`` is the HTTP status the API should return."""

    status = 400
    kind = "invalid_request_error"


class ToolRequestError(ToolCallError):
    """The request's tools, choice or history are malformed or unsupported."""


class ToolOutputError(ToolCallError):
    """The model produced an invalid, unterminated or missing required call."""

    status = 502
    kind = "tool_call_validation_failed"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: Optional[str]
    parameters: dict

    def for_template(self) -> dict:
        function = {"name": self.name, "parameters": self.parameters}
        if self.description:
            function["description"] = self.description
        return {"type": "function", "function": function}


@dataclass(frozen=True)
class ToolChoice:
    mode: str                     # none | auto | required | named
    name: Optional[str] = None

    @property
    def requires_call(self) -> bool:
        return self.mode in ("required", "named")


# ----------------------------------------------------------------------------
# JSON Schema subset
# ----------------------------------------------------------------------------
def check_schema(schema, where: str = "parameters", depth: int = 0) -> None:
    """Reject schema features this server cannot validate instead of ignoring them."""
    if depth > MAX_SCHEMA_DEPTH:
        raise ToolRequestError(f"{where}: schema nesting is deeper than {MAX_SCHEMA_DEPTH}")
    if not isinstance(schema, dict):
        raise ToolRequestError(f"{where}: a JSON Schema must be an object")
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise ToolRequestError(
            f"{where}: unsupported JSON Schema keyword(s) {', '.join(sorted(unknown))}"
        )
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not types or any(t not in _JSON_TYPES for t in types):
            raise ToolRequestError(f"{where}.type must name JSON types {_JSON_TYPES}")
    if "properties" in schema:
        props = schema["properties"]
        if not isinstance(props, dict):
            raise ToolRequestError(f"{where}.properties must be an object")
        for key, sub in props.items():
            check_schema(sub, f"{where}.properties.{key}", depth + 1)
    if "required" in schema:
        req = schema["required"]
        if not isinstance(req, list) or any(not isinstance(r, str) for r in req):
            raise ToolRequestError(f"{where}.required must be a list of property names")
    if "items" in schema:
        check_schema(schema["items"], f"{where}.items", depth + 1)
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        check_schema(schema["additionalProperties"], f"{where}.additionalProperties", depth + 1)
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise ToolRequestError(f"{where}.enum must be a non-empty list")
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            subs = schema[key]
            if not isinstance(subs, list) or not subs:
                raise ToolRequestError(f"{where}.{key} must be a non-empty list of schemas")
            for i, sub in enumerate(subs):
                check_schema(sub, f"{where}.{key}[{i}]", depth + 1)
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if key in schema and not _is_number(schema[key]):
            raise ToolRequestError(f"{where}.{key} must be a number")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and not (isinstance(schema[key], int) and not isinstance(schema[key], bool)
                                  and schema[key] >= 0):
            raise ToolRequestError(f"{where}.{key} must be a non-negative integer")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _type_matches(value, json_type: str) -> bool:
    if json_type == "null":
        return value is None
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "integer":
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, float) and value.is_integer())
    if json_type == "number":
        return _is_number(value)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    return False


def validate(value, schema: dict, path: str = "$") -> list:
    """Return schema violations (paths and expectations only, never values)."""
    errors: list = []
    _validate(value, schema, path, errors)
    return errors[:_MAX_ERRORS]


def _validate(value, schema: dict, path: str, errors: list) -> None:
    if len(errors) >= _MAX_ERRORS:
        return
    if value is None and schema.get("nullable") is True:
        return
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_matches(value, t) for t in types):
            errors.append(f"{path}: expected {' or '.join(types)}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: does not equal the required constant")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not one of the allowed values")
    if _is_number(value):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: not below {schema['exclusiveMaximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") is True:
            seen = [json.dumps(v, sort_keys=True) for v in value]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items are not unique")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{i}]", errors)
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(f"{path}.{name}: required property missing")
        extra = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name in props:
                _validate(item, props[name], f"{path}.{name}", errors)
            elif extra is False:
                errors.append(f"{path}.{name}: property not allowed")
            elif isinstance(extra, dict):
                _validate(item, extra, f"{path}.{name}", errors)
    if "allOf" in schema:
        for sub in schema["allOf"]:
            _validate(value, sub, path, errors)
    if "anyOf" in schema and not any(not validate(value, s, path) for s in schema["anyOf"]):
        errors.append(f"{path}: matches none of anyOf")
    if "oneOf" in schema and sum(1 for s in schema["oneOf"] if not validate(value, s, path)) != 1:
        errors.append(f"{path}: does not match exactly one of oneOf")


# ----------------------------------------------------------------------------
# Request
# ----------------------------------------------------------------------------
def normalize_tools(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ToolRequestError("tools must be a list")
    if len(raw) > MAX_TOOLS:
        raise ToolRequestError(f"at most {MAX_TOOLS} tools are supported")
    specs: list = []
    seen = set()
    for i, entry in enumerate(raw):
        where = f"tools[{i}]"
        if not isinstance(entry, dict) or entry.get("type") != "function":
            raise ToolRequestError(f'{where}: only type "function" tools are supported')
        function = entry.get("function")
        if not isinstance(function, dict):
            raise ToolRequestError(f"{where}.function must be an object")
        unknown = set(function) - {"name", "description", "parameters", "strict"}
        if unknown:
            raise ToolRequestError(f"{where}.function: unsupported field(s) {', '.join(sorted(unknown))}")
        name = function.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ToolRequestError(f"{where}.function.name must match [A-Za-z0-9_-]{{1,64}}")
        if name in seen:
            raise ToolRequestError(f"{where}: duplicate function name {name!r}")
        seen.add(name)
        description = function.get("description")
        if description is not None and not isinstance(description, str):
            raise ToolRequestError(f"{where}.function.description must be a string")
        parameters = function.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        check_schema(parameters, f"{where}.function.parameters")
        if parameters.get("type", "object") != "object":
            raise ToolRequestError(f'{where}.function.parameters must be a type "object" schema')
        specs.append(ToolSpec(name, description, parameters))
    return specs


def resolve_tool_choice(raw, tools: list) -> ToolChoice:
    if raw is None:
        return ToolChoice("auto" if tools else "none")
    if isinstance(raw, str):
        if raw not in ("none", "auto", "required"):
            raise ToolRequestError('tool_choice must be "none", "auto", "required" or a function')
        if raw != "none" and not tools:
            raise ToolRequestError(f'tool_choice "{raw}" requires tools')
        return ToolChoice(raw)
    if isinstance(raw, dict) and raw.get("type") == "function":
        function = raw.get("function")
        name = function.get("name") if isinstance(function, dict) else None
        if not any(t.name == name for t in tools):
            raise ToolRequestError("tool_choice names a function that is not in tools")
        return ToolChoice("named", name)
    raise ToolRequestError('tool_choice must be "none", "auto", "required" or a function')


def offered_tools(tools: list, choice: ToolChoice) -> list:
    """Definitions rendered into the prompt for this choice."""
    if choice.mode == "none":
        return []
    if choice.mode == "named":
        return [t for t in tools if t.name == choice.name]
    return list(tools)


def _content_text(content, where: str, allow_images: bool, images: list) -> str:
    """Flatten OpenAI content (string or parts) to text; collect image URLs."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ToolRequestError(f"{where}.content must be a string or a list of parts")
    texts, tags = [], []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            texts.append(str(part.get("text") or ""))
        elif isinstance(part, dict) and part.get("type") == "image_url":
            if not allow_images:
                raise ToolRequestError(f"{where}: images are only supported in user messages")
            url = (part.get("image_url") or {}).get("url")
            # Inline images only: conversation content is untrusted, so it
            # never names a server-side file or makes the server fetch a URL.
            if not isinstance(url, str) or not url.startswith("data:image/"):
                raise ToolRequestError(f"{where}: image_url must be a data:image/ URL")
            tags.append(MEDIA_TAG_FMT.format(len(images)))
            images.append(url)
        else:
            raise ToolRequestError(f"{where}: unsupported content part")
    return "".join(tags) + "\n".join(texts)


def normalize_history(messages: list) -> tuple:
    """Validate the ordered conversation and render-ready messages.

    Returns ``(template_messages, image_urls)``. Every assistant tool call must
    be answered by exactly one ``role: "tool"`` message before the conversation
    moves on; results must reference a call of the preceding assistant turn.
    """
    if not messages:
        raise ToolRequestError("messages must not be empty")
    out: list = []
    images: list = []
    known_ids: set = set()
    pending: dict = {}           # tool_call_id -> function name, for the open turn
    for i, msg in enumerate(messages):
        where = f"messages[{i}]"
        role = msg.get("role")
        if role != "tool" and pending:
            raise ToolRequestError(
                f"{where}: tool call(s) {', '.join(sorted(pending))} have no tool result"
            )
        if role in ("system", "developer"):
            text = _content_text(msg.get("content"), where, False, images)
            out.append({"role": "system", "content": text})
        elif role == "user":
            text = _content_text(msg.get("content"), where, True, images)
            if not text.strip():
                raise ToolRequestError(f"{where}: user content is required")
            out.append({"role": "user", "content": text})
        elif role == "assistant":
            text = _content_text(msg.get("content"), where, False, images)
            calls = msg.get("tool_calls") or []
            if not isinstance(calls, list):
                raise ToolRequestError(f"{where}.tool_calls must be a list")
            if not calls and not text:
                raise ToolRequestError(f"{where}: assistant message needs content or tool_calls")
            rendered = []
            for j, call in enumerate(calls):
                cw = f"{where}.tool_calls[{j}]"
                if not isinstance(call, dict) or call.get("type", "function") != "function":
                    raise ToolRequestError(f'{cw}: only type "function" calls are supported')
                call_id = call.get("id")
                if not isinstance(call_id, str) or not call_id:
                    raise ToolRequestError(f"{cw}.id is required")
                if call_id in known_ids:
                    raise ToolRequestError(f"{cw}.id duplicates an earlier call id")
                function = call.get("function")
                if not isinstance(function, dict):
                    raise ToolRequestError(f"{cw}.function must be an object")
                name = function.get("name")
                if not isinstance(name, str) or not name:
                    raise ToolRequestError(f"{cw}.function.name is required")
                arguments = _parse_arguments(function.get("arguments"), f"{cw}.function.arguments")
                known_ids.add(call_id)
                pending[call_id] = name
                rendered.append({"id": call_id, "type": "function",
                                 "function": {"name": name, "arguments": arguments}})
            entry = {"role": "assistant", "content": text}
            if rendered:
                entry["tool_calls"] = rendered
            if isinstance(msg.get("reasoning_content"), str):
                # Returned by this server; thinking templates keep it for the
                # turns of the current tool loop.
                entry["reasoning_content"] = msg["reasoning_content"]
            out.append(entry)
        elif role == "tool":
            call_id = msg.get("tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                raise ToolRequestError(f"{where}.tool_call_id is required")
            if call_id not in pending:
                reason = ("duplicates an earlier result" if call_id in known_ids
                          else "does not match a call of the preceding assistant turn")
                raise ToolRequestError(f"{where}.tool_call_id {reason}")
            text = _content_text(msg.get("content"), where, False, images)
            out.append({"role": "tool", "content": text, "tool_call_id": call_id,
                        "name": pending.pop(call_id)})
        else:
            raise ToolRequestError(f"{where}.role {role!r} is not supported")
    if pending:
        raise ToolRequestError(
            f"tool call(s) {', '.join(sorted(pending))} have no tool result"
        )
    if out[-1]["role"] not in ("user", "tool"):
        raise ToolRequestError("the last message must be a user or tool message")
    return out, images


def _parse_arguments(value, where: str) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value.strip() else {}
        except ValueError:
            raise ToolRequestError(f"{where} must be a JSON-encoded object") from None
        if isinstance(parsed, dict):
            return parsed
    raise ToolRequestError(f"{where} must be a JSON-encoded object")


def is_tool_conversation(tools, tool_choice, messages: list) -> bool:
    """Whether a request uses the tool contract (otherwise the legacy chat path)."""
    if tools or tool_choice is not None:
        return True
    return any(m.get("role") == "tool" or m.get("tool_calls") for m in messages)


# ----------------------------------------------------------------------------
# Model output
# ----------------------------------------------------------------------------
_XML_FUNCTION_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.DOTALL)
_XML_PARAM_RE = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.DOTALL)


def new_call_id() -> str:
    return "call_" + uuid.uuid4().hex[:24]


def parse_call_body(body: str, tools: list) -> tuple:
    """Parse one ``<tool_call>`` body into ``(name, arguments)``."""
    text = body.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError:
            raise ToolOutputError("model produced a tool call that is not valid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("name"), str):
            raise ToolOutputError("model produced a tool call without a function name")
        args = data.get("arguments", data.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                raise ToolOutputError("model produced tool arguments that are not JSON") from None
        if not isinstance(args, dict):
            raise ToolOutputError("model produced tool arguments that are not an object")
        return data["name"], args
    match = _XML_FUNCTION_RE.search(text)
    if match:
        name = match.group(1)
        spec = next((t for t in tools if t.name == name), None)
        props = (spec.parameters.get("properties") or {}) if spec else {}
        args = {}
        for pname, raw in _XML_PARAM_RE.findall(match.group(2)):
            value = raw[1:] if raw.startswith("\n") else raw
            value = value[:-1] if value.endswith("\n") else value
            args[pname] = _xml_value(value, props.get(pname) or {})
        return name, args
    raise ToolOutputError("model produced an unrecognized tool-call format")


def _xml_value(value: str, schema: dict):
    types = schema.get("type")
    types = types if isinstance(types, list) else ([types] if types else [])
    if not types or "string" in types:
        return value
    try:
        return json.loads(value)
    except ValueError:
        # Left as text: schema validation then reports the type mismatch.
        return value


def check_call(name: str, args: dict, tools: list, choice: ToolChoice) -> None:
    spec = next((t for t in offered_tools(tools, choice) if t.name == name), None)
    if spec is None:
        raise ToolOutputError("model called a function that was not offered")
    errors = validate(args, spec.parameters, "arguments")
    if errors:
        raise ToolOutputError("model produced invalid arguments: " + "; ".join(errors))


def _call_payload(name: str, args: dict) -> dict:
    return {"id": new_call_id(), "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}


@dataclass
class ParsedTurn:
    content: str
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"
    reasoning: str = ""


def parse_completion(text: str, tools: list, choice: ToolChoice, *, parallel: bool = True,
                     truncated: bool = False, reasoning_open: bool = False,
                     prefill: str = "") -> ParsedTurn:
    """Parse a complete generation (non-streaming)."""
    parser = ToolStreamParser(tools, choice, parallel=parallel, reasoning_open=reasoning_open,
                              prefill=prefill)
    events = parser.feed(text) + parser.finish(truncated)
    content = "".join(v for kind, v in events if kind == "content")
    reasoning = "".join(v for kind, v in events if kind == "reasoning").strip()
    calls = ([v for kind, v in events if kind == "call"]
             if parser.finish_reason == "tool_calls" else [])
    return ParsedTurn(content, calls, parser.finish_reason, reasoning)


class ToolStreamParser:
    """Incremental parser: emits text as it becomes safe, calls once validated.

    ``feed`` returns ``("content", str)``, ``("reasoning", str)`` and
    ``("call", dict)`` events. Text that might begin a ``<tool_call>`` or
    ``<think>`` tag is held back until it is decided; whitespace around the
    tags is not content. Calls inside reasoning are never parsed. With
    ``reasoning_open`` the prompt already opened ``<think>`` (thinking models),
    so output starts inside reasoning; ``prefill`` is prompt text the output
    continues (the opening of a forced call).
    """

    def __init__(self, tools: list, choice: ToolChoice, *, parallel: bool = True,
                 reasoning_open: bool = False, prefill: str = "") -> None:
        self.tools = tools
        self.choice = choice
        self.parallel = parallel
        self._parse_calls = choice.mode != "none"
        self._buffer = ""
        self._in_think = reasoning_open
        self._in_call = False
        self._calls = 0
        self._content_started = False
        self._pending_space = ""
        self.finish_reason: Optional[str] = None
        self.feed(prefill)  # an unfinished call opening yields no events

    def feed(self, text: str) -> list:
        self._buffer += text
        events: list = []
        while True:
            if self._in_call:
                end = self._buffer.find(TOOL_CLOSE)
                if end < 0:
                    return events
                body, self._buffer = self._buffer[:end], self._buffer[end + len(TOOL_CLOSE):]
                self._in_call = False
                if self._calls and not self.parallel:
                    continue  # parallel_tool_calls: false keeps the first call only
                name, args = parse_call_body(body, self.tools)
                check_call(name, args, self.tools, self.choice)
                self._calls += 1
                events.append(("call", _call_payload(name, args)))
                continue
            if self._in_think:
                end = self._buffer.find(THINK_CLOSE)
                if end < 0:
                    events += self._emit_safe((THINK_CLOSE,), "reasoning")
                    return events
                if end:
                    events.append(("reasoning", self._buffer[:end]))
                self._buffer = self._buffer[end + len(THINK_CLOSE):]
                self._in_think = False
                continue
            markers = (THINK_OPEN, TOOL_OPEN) if self._parse_calls else (THINK_OPEN,)
            hits = [(self._buffer.find(m), m) for m in markers if self._buffer.find(m) >= 0]
            if not hits:
                events += self._emit_safe(markers, "content")
                return events
            pos, marker = min(hits)
            events += self._content(self._buffer[:pos])
            if marker == THINK_OPEN:
                self._in_think = True
            else:
                self._in_call = True
                self._pending_space = ""
            self._buffer = self._buffer[pos + len(marker):]

    def _content(self, text: str) -> list:
        """Content without leading/trailing whitespace; inner whitespace is kept."""
        text = self._pending_space + text
        if not self._content_started:
            text = text.lstrip()
        body = text.rstrip()
        self._pending_space = text[len(body):]
        if not body:
            return []
        self._content_started = True
        return [("content", body)]

    def _emit_safe(self, markers: tuple, kind: str) -> list:
        """Emit the buffer except a suffix that could still start a marker."""
        hold = 0
        for marker in markers:
            for n in range(min(len(marker) - 1, len(self._buffer)), 0, -1):
                if self._buffer.endswith(marker[:n]):
                    hold = max(hold, n)
                    break
        out = self._buffer[:len(self._buffer) - hold]
        self._buffer = self._buffer[len(self._buffer) - hold:]
        if kind == "content":
            return self._content(out)
        return [(kind, out)] if out else []

    def finish(self, truncated: bool) -> list:
        """Flush the stream; decide ``finish_reason`` or raise ToolOutputError."""
        events: list = []
        if self._in_call:
            if not truncated:
                raise ToolOutputError("model ended inside an unterminated tool call")
            # Cut off by the token limit: report truncation, never a partial call.
            self._buffer = ""
            self.finish_reason = "length"
            return events
        if self._buffer:
            events += ([("reasoning", self._buffer)] if self._in_think
                       else self._content(self._buffer))
            self._buffer = ""
        if truncated:
            # A turn cut off by the token limit is not a successful tool
            # invocation, even if calls before the cut were complete.
            self.finish_reason = "length"
        elif self._calls:
            self.finish_reason = "tool_calls"
        elif self.choice.requires_call:
            raise ToolOutputError("model did not produce the required tool call")
        else:
            self.finish_reason = "stop"
        return events
