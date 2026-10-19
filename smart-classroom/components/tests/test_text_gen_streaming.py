# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""Streaming lifecycle of the warm VLM: cancellation, slot release, timing.

A fake pipeline stands in for ``VLMPipeline``; it emits tokens through the real
``YieldingTextStreamer`` and honours its stop flag the way the runtime does.
"""

import threading
import time
from types import SimpleNamespace

import pytest

ov_genai = pytest.importorskip("openvino_genai")
pytest.importorskip("transformers")

from components.vlm import text_gen_vlm  # noqa: E402
from components.vlm.text_gen_profiles import UnsupportedRequestError  # noqa: E402
from model_manager.capability.runner import CapabilityRunner  # noqa: E402
from utils import processing_stats as ps  # noqa: E402


class _Tokenizer:
    chat_template = "{% for m in messages %}{{ m.content }}{% endfor %}{% if tools %}tools{% endif %}"

    def decode(self, ids, skip_special_tokens=True):
        return "".join(f"t{i} " for i in ids)

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kw):
        tail = "<think>\n" if kw.get("enable_thinking") else ""
        return "|".join(str(m["content"]) for m in messages) + ("|TOOLS" if kw.get("tools") else "") + tail


class _Perf:
    def __init__(self, n):
        self.n = n

    def get_ttft(self):
        return SimpleNamespace(mean=12.5)

    def get_tpot(self):
        return SimpleNamespace(mean=4.0)

    def get_num_input_tokens(self):
        return 7

    def get_num_generated_tokens(self):
        return self.n

    def get_generate_duration(self):
        return SimpleNamespace(mean=50.0)


class _Pipe:
    """Writes up to max_new_tokens tokens, stopping when the streamer says so."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.prompts = []
        self.finished = threading.Event()

    def generate(self, prompt, generation_config=None, streamer=None, images=None):
        self.prompts.append(prompt)
        produced = 0
        try:
            for i in range(generation_config.max_new_tokens):
                produced += 1
                if streamer is not None:
                    status = streamer.write(i)
                    if status != ov_genai.StreamingStatus.RUNNING:
                        break
                time.sleep(self.delay)
        finally:
            self.finished.set()
        return SimpleNamespace(perf_metrics=_Perf(produced), __str__=lambda self: "done")


def _vlm(pipe, speculative=None):
    vlm = text_gen_vlm.VLMTextGen.__new__(text_gen_vlm.VLMTextGen)
    vlm._pipe = pipe
    vlm.tokenizer = _Tokenizer()
    vlm._model_name = "Qwen/Qwen3.6-35B-A3B"
    vlm._device = "GPU"
    vlm._weight_format = "int4"
    vlm._max_new_tokens = 64
    vlm._speculative = speculative
    vlm._tool_calls = True
    vlm._xml_tool_calls = False
    vlm._plan = None
    vlm._status = {}
    return vlm


@pytest.fixture
def stats(monkeypatch):
    store = ps.ProcessingStats()
    monkeypatch.setattr(ps, "STATS", store)
    monkeypatch.setattr(ps, "_append_session_line", lambda record: None)
    return store


def test_stream_completes_and_records_runtime_metrics(stats):
    vlm = _vlm(_Pipe())
    info = {}
    call = ps.ModelCall("text_gen", recorder=stats)
    tokens = list(vlm.generate("hi", stream=True, max_new_tokens=5, call=call, finish_info=info))
    assert "".join(tokens).split() == ["t0", "t1", "t2", "t3", "t4"]
    assert info["output_tokens"] == 5 and info["truncated"] is True
    (record,) = stats.records()[1]
    assert record["status"] == "ok"
    assert record["ttft_ms"] == 12.5 and record["tpot_ms"] == 4.0 and record["decode_tps"] == 250.0
    assert record["decoding"] == "plain" and record["first_output_ms"] is not None


def test_stream_end_waits_for_results_when_runtime_ends_streamer_first():
    class _EndingPipe(_Pipe):
        def generate(self, prompt, generation_config=None, streamer=None, images=None):
            result = super().generate(prompt, generation_config, streamer, images)
            streamer.end()   # the runtime ends the streamer before returning
            time.sleep(0.05)
            return result

    info = {}
    list(_vlm(_EndingPipe()).generate("hi", stream=True, max_new_tokens=3, finish_info=info))
    assert info["output_tokens"] == 3 and info["truncated"] is True


def test_disconnect_cancels_native_generation_and_holds_slot_until_it_stops(stats):
    pipe = _Pipe(delay=0.01)
    vlm = _vlm(pipe)
    runner = CapabilityRunner(vlm.generate, max_concurrency=1, queue_max=1)
    call = ps.ModelCall("text_gen", recorder=stats)
    stream = runner.submit("hi", stream=True, max_new_tokens=10_000, call=call)
    next(stream)
    stream.close()  # what Starlette does when the client goes away
    assert pipe.finished.wait(5), "native generation kept running after the client left"
    deadline = time.time() + 5
    while runner._current_queue and time.time() < deadline:
        time.sleep(0.01)
    assert runner._current_queue == 0, "slot not released after native generation stopped"
    (record,) = stats.records()[1]
    assert record["status"] == "cancelled"
    assert record["client_cancelled_after_ms"] is not None
    assert record["output_tokens"] < 10_000


def test_close_before_first_token_cancels_and_releases_slot():
    pipe = _Pipe(delay=0.01)
    runner = CapabilityRunner(_vlm(pipe).generate, max_concurrency=1, queue_max=1)
    stream = runner.submit("hi", stream=True, max_new_tokens=10_000)
    stream.close()  # response closed before it ever advanced the stream
    stream.close()  # idempotent
    assert pipe.finished.wait(5), "native generation kept running after an early close"
    deadline = time.time() + 5
    while runner._current_queue and time.time() < deadline:
        time.sleep(0.01)
    assert runner._current_queue == 0, "slot leaked by a stream closed before its first token"
    with pytest.raises(StopIteration):
        next(stream)


def test_slot_is_not_released_while_native_work_continues():
    gate = threading.Event()

    class _SlowPipe(_Pipe):
        def generate(self, prompt, generation_config=None, streamer=None, images=None):
            streamer.write(0)
            gate.wait(5)   # native call still busy after the client left
            return super().generate(prompt, generation_config, None)

    vlm = _vlm(_SlowPipe())
    runner = CapabilityRunner(vlm.generate, max_concurrency=1, queue_max=1)
    stream = runner.submit("hi", stream=True, max_new_tokens=2)
    next(stream)
    stream.close()
    assert runner._current_queue == 1
    gate.set()
    deadline = time.time() + 5
    while runner._current_queue and time.time() < deadline:
        time.sleep(0.01)
    assert runner._current_queue == 0


def test_think_filter_still_applies_to_streams():
    class _ThinkTok(_Tokenizer):
        def decode(self, ids, skip_special_tokens=True):
            words = ["<think>", "hidden", "</think>", "shown", " "]
            return "".join(words[i] for i in ids if i < len(words))

    vlm = _vlm(_Pipe())
    vlm.tokenizer = _ThinkTok()
    out = "".join(vlm.generate("hi", stream=True, max_new_tokens=5, enable_thinking=False))
    assert "hidden" not in out and "shown" in out


def test_speculative_pipeline_rejects_sampling_before_generation():
    pipe = _Pipe()
    spec = SimpleNamespace(method="dflash", num_assistant_tokens=3)
    vlm = _vlm(pipe, speculative=spec)
    with pytest.raises(UnsupportedRequestError, match="greedy"):
        vlm.generate("hi", stream=False, temperature=0.7)
    assert pipe.prompts == []
    vlm.generate("hi", stream=False, temperature=0.0, max_new_tokens=2)
    config = vlm._generation_config(4, None)
    assert config.num_assistant_tokens == 3 and config.assistant_confidence_threshold == 0.0


def test_plain_generation_config_is_unchanged():
    config = _vlm(_Pipe())._generation_config(8, 0.5)
    assert config.max_new_tokens == 8 and config.do_sample is True
    assert not config.num_assistant_tokens  # 0 before 2026.4, None after


@pytest.mark.parametrize("text, expected", [
    ("drafter export of z-lab/Qwen3.6-35B-A3B-DFlash failed",
     "drafter export of z-lab/Qwen3.6-35B-A3B-DFlash failed"),
    (r"cannot open C:\Users\bob\models\x.xml now", "cannot open <path> now"),
    ("file /home/bob/m.xml missing", "file <path> missing"),
    (r"share \\host\s\f gone", "share <path> gone"),
])
def test_health_reasons_drop_local_paths_but_keep_repo_ids(text, expected):
    assert text_gen_vlm._sanitize(text) == expected


def test_tools_are_rendered_and_require_capability():
    pipe = _Pipe()
    vlm = _vlm(pipe)
    info = {}
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    vlm.generate(messages=[{"role": "user", "content": "q"}], stream=False, tools=tools,
                 enable_thinking=True, max_new_tokens=1, finish_info=info)
    assert pipe.prompts[-1].startswith("q|TOOLS") and info["reasoning_open"] is True
    vlm._tool_calls = False
    with pytest.raises(UnsupportedRequestError, match="tool calling"):
        vlm.generate("q", stream=False, tools=tools)


@pytest.mark.parametrize("xml, name, opening", [
    (False, "f", '<tool_call>\n{"name": "f", "arguments": '),
    (True, "f", "<tool_call>\n<function=f>\n"),
    (True, "", "<tool_call>\n"),
])
def test_forced_tool_call_closes_reasoning_and_opens_the_call(xml, name, opening):
    pipe = _Pipe()
    vlm = _vlm(pipe)
    vlm._xml_tool_calls = xml
    info = {}
    tools = [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]
    vlm.generate(messages=[{"role": "user", "content": "q"}], stream=False, tools=tools,
                 enable_thinking=True, max_new_tokens=1, force_tool_call=name, finish_info=info)
    assert pipe.prompts[-1] == "q|TOOLS<think>\n\n</think>\n\n" + opening
    assert info["prefill"] == opening and info["reasoning_open"] is False


def test_tool_conversation_never_falls_back_to_the_last_turn():
    class _Broken(_Tokenizer):
        def apply_chat_template(self, *args, **kwargs):
            raise ValueError("System message must be at the beginning.")

    pipe = _Pipe()
    vlm = _vlm(pipe)
    vlm.tokenizer = _Broken()
    history = [{"role": "user", "content": "q"},
               {"role": "assistant", "content": "", "tool_calls": [{"id": "c"}]},
               {"role": "tool", "content": "21", "tool_call_id": "c"}]
    with pytest.raises(UnsupportedRequestError, match="could not render"):
        vlm.generate(messages=history, stream=False)
    assert pipe.prompts == []
