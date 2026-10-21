# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0


from __future__ import annotations

import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List, Optional

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from components.vlm import tool_calls as tc
from components.vlm.text_gen_profiles import UnsupportedRequestError
from model_manager import ModelManager
from utils.processing_stats import stage_scope

logger = logging.getLogger(__name__)

router = APIRouter()

# Internal clients name their workflow stage so calls to the shared model stay
# attributable (Q&A, video captioning, grading); anything else is "chat_api".
STAGE_HEADER = "x-sc-stage"
_STAGE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _request_stage(request: Request) -> str:
    stage = (request.headers.get(STAGE_HEADER) or "").strip().lower()
    return stage if _STAGE_RE.match(stage) else "chat_api"

# smart-classroom root: api/vlm_chat.py -> parents[1]
_SC_ROOT = Path(__file__).resolve().parents[1]
_CONTENT_SEARCH_DIR = _SC_ROOT / "content_search"


def _import_vlm_serving() -> SimpleNamespace:

    if str(_CONTENT_SEARCH_DIR) not in sys.path:
        sys.path.append(str(_CONTENT_SEARCH_DIR))
    from components.vlm.vlm_openvino_serving.utils.data_models import (  # noqa: E402
        ChatCompletionChoice,
        ChatCompletionDelta,
        ChatCompletionResponse,
        ChatRequest,
        MessageContentImageUrl,
        MessageContentText,
    )
    from components.vlm.vlm_openvino_serving.utils.utils import load_images  # noqa: E402

    return SimpleNamespace(
        ChatRequest=ChatRequest,
        ChatCompletionResponse=ChatCompletionResponse,
        ChatCompletionChoice=ChatCompletionChoice,
        ChatCompletionDelta=ChatCompletionDelta,
        MessageContentText=MessageContentText,
        MessageContentImageUrl=MessageContentImageUrl,
        load_images=load_images,
    )


def _extract_prompt_and_images(messages, mods: SimpleNamespace):
    last_user_message = next(
        (m for m in reversed(messages) if m.role == "user"), None
    )
    image_urls: List[str] = []
    prompt: Optional[str] = None
    if last_user_message is not None:
        if isinstance(last_user_message.content, str):
            prompt = last_user_message.content
        else:
            for content in last_user_message.content or []:
                if isinstance(content, mods.MessageContentImageUrl):
                    url = content.image_url.get("url")
                    if url:
                        image_urls.append(url)
                elif isinstance(content, mods.MessageContentText):
                    prompt = content.text
                elif isinstance(content, str):
                    prompt = content
    return prompt, image_urls


def _model_name(requested: Optional[str]) -> str:
    try:
        from utils.config_loader import config

        name = getattr(getattr(config.models, "text_gen", None), "vlm_name", None)
        if name:
            return str(name)
    except Exception:  
        pass
    return requested or "text_gen"


def _chunk_writer(model_name: str):
    """SSE ``chat.completion.chunk`` formatter sharing one id and timestamp.

    ``chunk(delta, finish_reason)`` writes a choice delta; ``chunk(usage=...)``
    writes the OpenAI usage chunk, which carries no choices.
    """
    created = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"

    def chunk(delta: Optional[dict] = None, finish_reason: Optional[str] = None,
              usage: Optional[dict] = None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [] if usage is not None else [
                {"index": 0, "delta": delta, "finish_reason": finish_reason}
            ],
        }
        if usage is not None:
            payload["usage"] = usage
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return chunk


def _usage(info: dict) -> Optional[dict]:
    """OpenAI ``usage`` from runtime token counts; None when the runtime gave none.

    ``prompt_tokens`` is what the model prefilled, image tokens included.
    """
    prompt_tokens, completion_tokens = info.get("input_tokens"), info.get("output_tokens")
    if not (isinstance(prompt_tokens, int) and isinstance(completion_tokens, int)):
        return None
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens}


def _include_usage(chat_req) -> bool:
    return bool((chat_req.stream_options or {}).get("include_usage"))


def _finish_reason(info: dict) -> str:
    """``length`` when generation stopped at max_new_tokens, else ``stop``."""
    return "length" if info.get("truncated") else "stop"


def _close(token_iter) -> None:
    """Stop native generation if the client stopped reading early."""
    close = getattr(token_iter, "close", None)
    if close is not None:
        close()


def _error_event(message: str, kind: str) -> str:
    error = {"error": {"message": message, "type": kind, "code": None}}
    return f"data: {json.dumps(error, ensure_ascii=False)}\n\n"


# A failure after HTTP 200 has started (a runtime error, or OomError from the
# runner) is reported in-band; its details stay in the server log.
_GENERATION_FAILED = _error_event("generation failed", "server_error")


def _sse_stream(token_iter: Iterator[str], model_name: str, info: dict,
                include_usage: bool = False) -> Iterator[str]:
    chunk = _chunk_writer(model_name)
    try:
        # First chunk announces the assistant role (OpenAI convention).
        yield chunk({"role": "assistant"})
        for token in token_iter:
            if token:
                yield chunk({"content": token})
        # The iterator is exhausted, so the runtime has filled ``info``.
        yield chunk({}, finish_reason=_finish_reason(info))
        usage = _usage(info) if include_usage else None
        if usage is not None:
            yield chunk(usage=usage)
    except Exception:  # noqa: BLE001 - the stream has started; end it with an error
        logger.exception("Streaming generation failed")
        yield _GENERATION_FAILED
    finally:
        _close(token_iter)
    yield "data: [DONE]\n\n"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible chat completion backed by the warm in-process VLM."""
    # Model calls made while handling this request are attributed to the stage.
    with stage_scope(None, _request_stage(request)):
        return await _chat_completions(request)


async def _chat_completions(request: Request):
    mods = _import_vlm_serving()

    try:
        body = await request.json()
        chat_req = mods.ChatRequest(**body)
    except Exception as exc:  # noqa: BLE001 - malformed body / schema violation
        return JSONResponse(
            status_code=400, content={"error": f"Invalid request: {exc}"}
        )

    messages = [m.model_dump(exclude_none=True) for m in chat_req.messages]
    if tc.is_tool_conversation(chat_req.tools, chat_req.tool_choice, messages):
        # Full ordered history, tool definitions and tool results.
        return await _tool_chat_completions(chat_req, messages, mods)

    prompt, image_urls = _extract_prompt_and_images(chat_req.messages, mods)
    if not prompt or not prompt.strip():
        return JSONResponse(status_code=400, content={"error": "Prompt is required"})
    if any(not url.startswith("data:image/") for url in image_urls):
        # Inline images only: request content never names a server-side file
        # (any web page can reach this loopback API) or makes the server fetch.
        return JSONResponse(status_code=400,
                            content={"error": "image_url must be a data:image/ URL"})

    image_tensors = None
    if image_urls:
        try:
            _, image_tensors = await mods.load_images(image_urls)
        except (ValueError, RuntimeError) as exc:  # unreadable or undecodable image
            return JSONResponse(status_code=400, content={"error": str(exc)})

    model_name = _model_name(chat_req.model)
    handler = ModelManager.instance().text_gen()
    # Filled by the runtime once generation ends: token counts and truncation.
    info: dict = {}

    try:
        if chat_req.stream:
            # Admission waits on a threading semaphore: keep it off the event loop.
            token_iter = await run_in_threadpool(
                handler.generate,
                prompt,
                images=image_tensors,
                stream=True,
                max_new_tokens=chat_req.max_completion_tokens,
                temperature=chat_req.temperature,
                enable_thinking=chat_req.enable_thinking,
                finish_info=info,
            )
            return StreamingResponse(
                _sse_stream(token_iter, model_name, info, _include_usage(chat_req)),
                media_type="text/event-stream",
            )

        output = await run_in_threadpool(
            handler.generate,
            prompt,
            images=image_tensors,
            stream=False,
            max_new_tokens=chat_req.max_completion_tokens,
            temperature=chat_req.temperature,
            enable_thinking=chat_req.enable_thinking,
            finish_info=info,
        )
    except UnsupportedRequestError as exc:
        # Rejected before generation rather than silently changed.
        return JSONResponse(status_code=400, content={"error": str(exc)})
    response = mods.ChatCompletionResponse(
        id=str(uuid.uuid4()),
        object="chat.completion",
        created=int(time.time()),
        model=model_name,
        choices=[
            mods.ChatCompletionChoice(
                index=0,
                message=mods.ChatCompletionDelta(role="assistant", content=str(output)),
                finish_reason=_finish_reason(info),
            )
        ],
    )
    content = response.model_dump()
    content["usage"] = _usage(info)
    return JSONResponse(content=content)


# ---------------------------------------------------------------------------
# Tool calling
# ---------------------------------------------------------------------------
def _tool_error(status: int, message: str, kind: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": None}},
    )


async def _tool_chat_completions(chat_req, messages: list, mods: SimpleNamespace):
    """OpenAI function calling: validate, render with tools, parse and validate calls.

    The server returns calls; executing them is the client's decision.
    """
    try:
        tools = tc.normalize_tools(chat_req.tools)
        choice = tc.resolve_tool_choice(chat_req.tool_choice, tools)
        history, image_urls = tc.normalize_history(messages)
    except tc.ToolRequestError as exc:
        return _tool_error(exc.status, str(exc), exc.kind)

    model_name = _model_name(chat_req.model)
    handler = ModelManager.instance().text_gen()
    offered = tc.offered_tools(tools, choice)
    uses_tool_turns = any(m["role"] == "tool" or m.get("tool_calls") for m in history)
    # May load the model on first use: keep that off the event loop.
    if ((offered or uses_tool_turns)
            and not await run_in_threadpool(lambda: handler.supports_tools)):
        return _tool_error(400, f"{model_name} does not support tool calling",
                           "invalid_request_error")

    image_tensors = None
    if image_urls:
        try:
            _, image_tensors = await mods.load_images(image_urls)
        except (ValueError, RuntimeError) as exc:
            return _tool_error(400, str(exc), "invalid_request_error")

    parallel = chat_req.parallel_tool_calls is not False
    info: dict = {}
    kwargs = dict(
        messages=history,
        images=image_tensors,
        max_new_tokens=chat_req.max_completion_tokens,
        temperature=chat_req.temperature,
        enable_thinking=chat_req.enable_thinking,
        tools=[t.for_template() for t in offered] or None,
        finish_info=info,
    )
    if choice.requires_call:
        # "required" and named choices are enforced by starting the answer
        # with the call rather than hoping the model chooses one.
        kwargs["force_tool_call"] = choice.name or ""
    try:
        if chat_req.stream:
            token_iter = await run_in_threadpool(handler.generate, stream=True, **kwargs)
            # Positioned after the prompt: inside reasoning or a forced call.
            parser = tc.ToolStreamParser(tools, choice, parallel=parallel,
                                         reasoning_open=bool(info.get("reasoning_open")),
                                         prefill=info.get("prefill") or "")
            return StreamingResponse(
                _tool_sse_stream(token_iter, parser, info, model_name,
                                 _include_usage(chat_req)),
                media_type="text/event-stream",
            )
        output = await run_in_threadpool(handler.generate, stream=False, **kwargs)
    except UnsupportedRequestError as exc:
        return _tool_error(400, str(exc), "invalid_request_error")

    try:
        turn = tc.parse_completion(
            str(output), tools, choice, parallel=parallel,
            truncated=bool(info.get("truncated")),
            reasoning_open=bool(info.get("reasoning_open")),
            prefill=info.get("prefill") or "",
        )
    except tc.ToolOutputError as exc:
        # Never returned as a successful tool invocation.
        logger.warning("Rejected generated tool call: %s", exc)
        return _tool_error(exc.status, str(exc), exc.kind)

    message = {"role": "assistant", "content": turn.content or None}
    if turn.reasoning:
        message["reasoning_content"] = turn.reasoning
    if turn.tool_calls:
        message["tool_calls"] = turn.tool_calls
    return JSONResponse(content={
        "id": str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "system_fingerprint": None,
        "choices": [{"index": 0, "message": message, "finish_reason": turn.finish_reason}],
        "usage": _usage(info),
    })


# Parser event -> SSE delta field.
_DELTA_FIELD = {"content": "content", "reasoning": "reasoning_content"}


def _tool_sse_stream(token_iter, parser: "tc.ToolStreamParser", info: dict,
                     model_name: str, include_usage: bool = False) -> Iterator[str]:
    """SSE with buffered tool calls: a call is published only once complete and valid."""
    chunk = _chunk_writer(model_name)
    calls = []
    try:
        yield chunk({"role": "assistant"})
        for token in token_iter:
            for kind, value in parser.feed(token):
                if kind == "call":
                    calls.append(value)
                else:
                    yield chunk({_DELTA_FIELD[kind]: value})
        for kind, value in parser.finish(bool(info.get("truncated"))):
            yield chunk({_DELTA_FIELD[kind]: value})
        if parser.finish_reason == "tool_calls":
            # Held until the turn is known complete: like the non-streaming
            # path, a truncated turn publishes none of its calls.
            for index, call in enumerate(calls):
                yield chunk({"tool_calls": [{"index": index, **call}]})
        yield chunk({}, finish_reason=parser.finish_reason)
        usage = _usage(info) if include_usage else None
        if usage is not None:
            yield chunk(usage=usage)
    except tc.ToolOutputError as exc:
        # Terminate with an error instead of claiming a tool-call finish.
        logger.warning("Rejected generated tool call mid-stream: %s", exc)
        yield _error_event(str(exc), exc.kind)
    except Exception:  # noqa: BLE001 - the stream has started; end it with an error
        logger.exception("Streaming generation failed")
        yield _GENERATION_FAILED
    finally:
        _close(token_iter)
    yield "data: [DONE]\n\n"
