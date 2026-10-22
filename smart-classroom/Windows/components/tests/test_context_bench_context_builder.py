# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Prompt construction: exact sizing, single templating, standalone context zero, probe
placement and tolerance, and the task framings -- all with a word-level stub tokenizer."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from components.context_bench import context_builder, report, settings, trial_runner
from components.context_bench.context_builder import (
    MAX_CORRECTION_PASSES,
    PromptSizeError,
    build_benchmark_prompt,
    build_probe_prompt,
    build_text_of_token_length,
    render_prompt,
)
from components.context_bench.trial_runner import prepare_pipeline_input


class FakeTokenizer:
    """Word-level stub: one id per distinct whitespace word, exact encode/decode round trip."""

    def __init__(self):
        self._id_to_word = []
        self._word_to_id = {}
        self.renders = []

    def encode(self, text, add_special_tokens=True):
        ids = []
        for word in text.split():
            if word not in self._word_to_id:
                self._word_to_id[word] = len(self._id_to_word)
                self._id_to_word.append(word)
            ids.append(self._word_to_id[word])
        return ids

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(self._id_to_word[i] for i in ids)

    def apply_chat_template(self, messages, tokenize=False, **kwargs):
        self.renders.append(([dict(m) for m in messages], dict(kwargs)))
        return " ".join(f"<{m['role']}> {m.get('content', '')}" for m in messages) + " <assistant>"


class BoundaryDriftTokenizer(FakeTokenizer):
    def apply_chat_template(self, messages, tokenize=False, **kwargs):
        rendered = super().apply_chat_template(messages, tokenize=tokenize, **kwargs)
        return rendered + (" boundary-token" if messages[-1].get("content") else "")


class OrbitingTokenizer(FakeTokenizer):
    """A rendered prompt always measures an odd count: an even target is unreachable."""

    def encode(self, text, add_special_tokens=True):
        ids = super().encode(text, add_special_tokens)
        if "<system>" in text and len(ids) % 2 == 0:
            ids = ids + [0]
        return ids


def _fake_genai():
    class GenerationConfig:
        pass

    return types.SimpleNamespace(
        GenerationConfig=GenerationConfig,
        StreamingStatus=types.SimpleNamespace(RUNNING="running"),
    )


class TestExactPositiveContext(unittest.TestCase):
    def test_zero_tokens_is_empty_text(self):
        self.assertEqual(build_text_of_token_length(FakeTokenizer(), 0), "")

    def test_rendered_prompt_lands_exactly_on_the_target(self):
        for target in (500, 8000, 160000):
            with self.subTest(target=target):
                tok = FakeTokenizer()
                prompt, count = build_benchmark_prompt(tok, target)
                self.assertEqual(count, target)
                self.assertEqual(len(tok.encode(prompt)), target)
                self.assertIn("CLASSROOM TRANSCRIPT", prompt)

    def test_boundary_drift_is_corrected_within_the_pass_bound(self):
        tok = BoundaryDriftTokenizer()
        _, count = build_benchmark_prompt(tok, 8000)
        self.assertEqual(count, 8000)
        # One scaffolding render plus at most MAX_CORRECTION_PASSES candidate renders.
        self.assertLessEqual(len(tok.renders), 1 + MAX_CORRECTION_PASSES)

    def test_non_convergence_fails_explicitly_after_the_bounded_passes(self):
        tok = OrbitingTokenizer()
        with self.assertRaisesRegex(PromptSizeError, f"{MAX_CORRECTION_PASSES} correction passes"):
            build_benchmark_prompt(tok, 2000)
        self.assertEqual(len(tok.renders), 1 + MAX_CORRECTION_PASSES)

    def test_a_budget_smaller_than_the_scaffolding_is_rejected_up_front(self):
        with self.assertRaisesRegex(PromptSizeError, "smaller than the .*scaffolding"):
            build_benchmark_prompt(FakeTokenizer(), 5)

    def test_empty_transcript_prices_only_the_scaffolding(self):
        tok = FakeTokenizer()
        prompt, overhead = render_prompt(tok, "", add_generation_prompt=True)
        self.assertEqual(overhead, len(tok.encode(prompt)))
        self.assertLess(overhead, 50)


class TestSingleTemplating(unittest.TestCase):
    def test_each_candidate_is_templated_once_and_never_nested(self):
        tok = FakeTokenizer()
        prompt, _ = build_benchmark_prompt(tok, 3000)
        self.assertEqual(prompt.count("<system>"), 1)
        self.assertEqual(prompt.count("<user>"), 1)
        for messages, kwargs in tok.renders:
            # The content fed to the template never contains an already rendered prompt.
            self.assertTrue(all("<system>" not in m["content"] for m in messages))
            self.assertEqual(kwargs, {"add_generation_prompt": True, "enable_thinking": False})

    def test_the_pipeline_does_not_apply_a_second_chat_template(self):
        with mock.patch.dict(sys.modules, {"openvino_genai": _fake_genai()}):
            config = trial_runner.generation_config(64)
            speculative = trial_runner.generation_config(
                64, {"enabled": True, "num_assistant_tokens": 3})
        self.assertFalse(getattr(config, "apply_chat_template", False))
        self.assertFalse(config.do_sample)
        self.assertFalse(config.ignore_eos)
        self.assertEqual(config.num_return_sequences, 1)
        self.assertEqual(config.num_assistant_tokens, 0)
        self.assertEqual(config.assistant_confidence_threshold, 0.0)
        self.assertEqual(speculative.num_assistant_tokens, 3)

    def test_llm_receives_the_counted_tokenized_input(self):
        tokenized = SimpleNamespace(input_ids=SimpleNamespace(shape=(1, 160000)))
        pipe = SimpleNamespace(get_tokenizer=lambda: SimpleNamespace(encode=lambda _p: tokenized))
        pipeline_input, count = prepare_pipeline_input(pipe, "prompt", True)
        self.assertIs(pipeline_input, tokenized)
        self.assertEqual(count, 160000)

    def test_vlm_keeps_the_validated_string(self):
        tokenized = SimpleNamespace(input_ids=SimpleNamespace(shape=(1, 77)))
        pipe = SimpleNamespace(get_tokenizer=lambda: SimpleNamespace(encode=lambda _p: tokenized))
        pipeline_input, count = prepare_pipeline_input(pipe, "prompt", False)
        self.assertEqual((pipeline_input, count), ("prompt", 77))


class TestVlmRuntimeCountMismatch(unittest.TestCase):
    """VLMPipeline tokenizes the string itself; a runtime count that differs from the
    counted prompt invalidates exact-context certification but keeps the timings."""

    def _generate(self, runtime_input):
        perf = SimpleNamespace(
            get_ttft=lambda: SimpleNamespace(mean=100.0),
            get_tpot=lambda: SimpleNamespace(mean=50.0),
            get_generate_duration=lambda: SimpleNamespace(mean=300.0),
            get_num_generated_tokens=lambda: 5,
            get_num_input_tokens=lambda: runtime_input,
        )

        class Pipe:
            def get_tokenizer(self):
                return None

            def generate(self, _input, generation_config, streamer):
                streamer("a")
                return SimpleNamespace(texts=["a b c d e"], perf_metrics=perf)

        channel = SimpleNamespace(post=lambda *a, **k: None)
        with mock.patch.dict(sys.modules, {"openvino_genai": _fake_genai()}):
            return trial_runner._generate_once(
                Pipe(), "prompt", channel, trial_runner._Progress(), 0, False, 64,
                {"ov_tokens": 101, "prompt_sha256": "h"}, {}, "c001")

    def test_mismatch_is_flagged_and_timings_are_kept(self):
        record = self._generate(runtime_input=104)
        self.assertTrue(record["input_count_mismatch"])
        self.assertEqual(record["input_size"], 104)
        self.assertEqual(record["other_tokens_avg_latency"], 50.0)

    def test_matching_runtime_count_is_not_flagged(self):
        self.assertFalse(self._generate(runtime_input=101)["input_count_mismatch"])


class TestStandaloneContextZero(unittest.TestCase):
    def test_domain_tasks_render_standalone_at_their_natural_length(self):
        for name in ("math", "code", "chat"):
            with self.subTest(task=name):
                task = settings.throughput_task_prompt(name, "Qwen3.6-35B-A3B")
                tok = FakeTokenizer()
                prompt, count = build_benchmark_prompt(tok, 0, task)
                self.assertEqual(count, len(FakeTokenizer().encode(prompt)))
                self.assertNotIn("CLASSROOM TRANSCRIPT", prompt)
                self.assertNotIn("context only", prompt)
                self.assertIn(task["standalone"]["user"], prompt)

    def test_a_summary_of_nothing_is_refused(self):
        for task in (None, {"name": "classroom_summary"}):
            with self.subTest(task=task), self.assertRaisesRegex(PromptSizeError, "standalone"):
                build_benchmark_prompt(FakeTokenizer(), 0, task)

    def test_domain_tasks_keep_the_transcript_at_positive_context(self):
        task = settings.throughput_task_prompt("math", "Qwen3.6-35B-A3B")
        prompt, count = build_benchmark_prompt(FakeTokenizer(), 5000, task)
        self.assertEqual(count, 5000)
        self.assertIn("CLASSROOM TRANSCRIPT", prompt)
        self.assertIn("Answer: <number>", prompt)
        self.assertNotIn("two concise sentences", prompt)


class TestClassroomSummaryFraming(unittest.TestCase):
    """The application's current summarizer request, read without its config singleton."""

    def _app_config(self, root, language="en", mode="teacher"):
        path = Path(root, "config.yaml")
        path.write_text(f"app:\n  language: {language}\nmodels:\n  summarizer:\n    mode: {mode}\n",
                        encoding="utf-8")
        return path

    def test_template_language_and_mode_come_from_the_application(self):
        with tempfile.TemporaryDirectory() as root:
            task = settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B",
                                                   self._app_config(root, mode="teacher"))
        expected = (settings.SC_ROOT / "prompts" / "summarizer" / "en" / "teacher.txt").read_text(
            encoding="utf-8").rstrip("\n")
        self.assertEqual(task["system_prompt"], expected)
        self.assertEqual((task["language"], task["summary_mode"]), ("en", "teacher"))
        self.assertEqual(task["suffix"], "")
        self.assertEqual(len(task["template_sha256"]), 64)

    def test_the_resolved_language_is_part_of_the_task_identity_and_its_label(self):
        # config.yaml can change between runs; a zh and an en summary must never read as one
        # workload, in the comparison key or in a report.
        with tempfile.TemporaryDirectory() as root:
            en = settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B",
                                                 self._app_config(root, language="en", mode="dialog"))
            zh = settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B",
                                                 self._app_config(root, language="zh", mode="dialog"))
        self.assertNotEqual(settings.task_sha256(en), settings.task_sha256(zh))
        self.assertEqual((settings.task_variant(en), settings.task_variant(zh)),
                         ("en, dialog", "zh, dialog"))
        self.assertIsNone(settings.task_variant(settings.throughput_task_prompt("chat", "q")))
        self.assertIsNone(settings.task_variant(None))
        self.assertEqual(report.task_label({"throughput_task": "classroom_summary",
                                            "task_variant": "zh, dialog"}),
                         "classroom_summary (zh, dialog)")
        self.assertEqual(report.task_label({"throughput_task": "chat"}), "chat")

    def test_unknown_mode_falls_back_to_dialog_like_the_component(self):
        with tempfile.TemporaryDirectory() as root:
            task = settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B",
                                                   self._app_config(root, mode="other"))
        self.assertEqual(task["summary_mode"], "dialog")

    def test_no_think_follows_the_applications_renderer_not_a_name_substring(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._app_config(root)
            moe = settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B", config)
            dense = settings.throughput_task_prompt("classroom_summary", "Qwen3-8B", config)
        self.assertEqual(moe["user_prefix"], "")
        self.assertEqual(dense["user_prefix"], "/no_think\n")

    def test_an_unresolvable_template_is_a_configuration_error(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(settings.ConfigError, "could not resolve"):
                settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B",
                                                self._app_config(root, language="xx"))
            with self.assertRaises(settings.ConfigError):
                settings.throughput_task_prompt("classroom_summary", "q", Path(root, "missing.yaml"))

    def test_the_request_is_sized_exactly_with_synthetic_content(self):
        with tempfile.TemporaryDirectory() as root:
            task = settings.throughput_task_prompt("classroom_summary", "Qwen3.6-35B-A3B",
                                                   self._app_config(root))
        prompt, count = build_benchmark_prompt(FakeTokenizer(), 6000, task)
        self.assertEqual(count, 6000)
        self.assertIn("TEACHER:", prompt)
        self.assertNotIn("CLASSROOM TRANSCRIPT", prompt)


class TestProbePlacement(unittest.TestCase):
    def test_multiple_inserts_keep_depth_order_and_the_total_size(self):
        inserts = [(0.8, "MARKER_LAST here"), (0.1, "MARKER_FIRST here"), (0.5, "MARKER_MID here")]
        prompt, count = build_probe_prompt(FakeTokenizer(), 4000, inserts, "Where?")
        self.assertEqual(count, 4000)
        self.assertLess(prompt.index("MARKER_FIRST"), prompt.index("MARKER_MID"))
        self.assertLess(prompt.index("MARKER_MID"), prompt.index("MARKER_LAST"))

    def test_cumulative_split_sums_to_the_filler_budget(self):
        tok = FakeTokenizer()
        ordered = [(0.333, "XQA"), (0.334, "XQB"), (0.667, "XQC")]
        text = context_builder._weave(tok, ordered, 1000, None)
        filler_words = [w for w in text.split() if w not in ("XQA", "XQB", "XQC")]
        self.assertEqual(len(filler_words), 1000)

    def test_depth_moves_an_insert_from_top_to_bottom(self):
        needle = "MARKERNEEDLEXYZ planted here"
        top, _ = build_probe_prompt(FakeTokenizer(), 2000, [(0.0, needle)], "Where?")
        bottom, _ = build_probe_prompt(FakeTokenizer(), 2000, [(1.0, needle)], "Where?")
        self.assertLess(top.index("MARKERNEEDLEXYZ") / len(top), 0.35)
        self.assertGreater(bottom.index("MARKERNEEDLEXYZ") / len(bottom), 0.6)

    def test_sixteen_token_probe_tolerance(self):
        self.assertEqual(trial_runner.PROBE_TOKEN_TOLERANCE, 16)
        with self.assertRaisesRegex(PromptSizeError, "within 0 token"):
            build_probe_prompt(OrbitingTokenizer(), 2000, [(0.5, "needle")], "q?")
        _, count = build_probe_prompt(OrbitingTokenizer(), 2000, [(0.5, "needle")], "q?",
                                      tolerance=trial_runner.PROBE_TOKEN_TOLERANCE)
        self.assertNotEqual(count, 2000)
        self.assertLessEqual(abs(count - 2000), 16)

    def test_a_context_too_small_for_the_inserts_is_rejected(self):
        with self.assertRaisesRegex(PromptSizeError, "cannot hold"):
            build_probe_prompt(FakeTokenizer(), 10, [(0.5, " ".join(["word"] * 50))], "q?")

    def test_a_depth_outside_the_unit_interval_is_rejected(self):
        with self.assertRaisesRegex(PromptSizeError, "depth must be in"):
            build_probe_prompt(FakeTokenizer(), 400, [(1.5, "needle")], "q?")


if __name__ == "__main__":
    unittest.main()
