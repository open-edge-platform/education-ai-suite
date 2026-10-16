# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Accuracy suites without a model: deterministic probes, option validation, exact probe
counts, ground truth that survives filler truncation, scorer golden cases, cross-case
fidelity pairing, skipped-probe denominators, optional WWB and text persistence policy."""

import inspect
import random
import subprocess
import sys
import types
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from components.context_bench import (
    accuracy,
    benchmark,
    evidence,
    report,
    scoring,
    settings,
    tasks,
    trial_runner,
    wwb_adapter,
)
from components.context_bench.context_builder import build_probe_prompt, corpus_text

SC_ROOT = Path(__file__).resolve().parents[2]


class FakeTokenizer:
    def __init__(self):
        self._words, self._ids = [], {}

    def encode(self, text, add_special_tokens=True):
        out = []
        for word in text.split():
            if word not in self._ids:
                self._ids[word] = len(self._words)
                self._words.append(word)
            out.append(self._ids[word])
        return out

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(self._words[i] for i in ids)

    def apply_chat_template(self, messages, tokenize=False, **kwargs):
        return " ".join(f"<{m['role']}> {m['content']}" for m in messages)


def _spec(task, depth=0.5, sample=0, seed=123, context=8000, options=None):
    return tasks.build_spec(task=task, sample=sample, depth=depth, haystack=corpus_text(), seed=seed,
                            context_tokens=context, output_tokens=64, options=options or {})


def _cfg(**overrides):
    cfg = {
        "suites": [accuracy.SUITE_RETRIEVAL, accuracy.SUITE_GENERATION],
        "baseline_profile": "paged_min", "seed": 123, "embedding_model": None,
        accuracy.SUITE_RETRIEVAL: {"tasks": ["niah_single", "vt"], "depths": [0.0, 1.0], "samples": 2,
                                   "output_tokens": 64, "options": {}},
        accuracy.SUITE_GENERATION: {"tasks": ["summary", "fact_sheet"], "depths": [0.5], "samples": 2,
                                    "output_tokens": 256, "options": {}},
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# Determinism and options
# ---------------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    def test_same_config_same_probe_and_every_coordinate_differs(self):
        self.assertEqual(_spec("niah_single").truths, _spec("niah_single").truths)
        self.assertEqual(_spec("vt").fixture_id, _spec("vt").fixture_id)
        values = [_spec("niah_single", depth=d, sample=s).truths[0] for d in (0.0, 0.5, 1.0) for s in range(3)]
        self.assertEqual(len(set(values)), len(values))
        self.assertNotEqual(_spec("niah_single", context=8000).truths, _spec("niah_single", context=32000).truths)
        self.assertNotEqual(_spec("niah_single", seed=1).fixture_id, _spec("niah_single", seed=2).fixture_id)

    def test_planted_values_are_identical_across_processes(self):
        code = ("from components.context_bench import tasks; from components.context_bench.context_builder "
                "import corpus_text; s = tasks.build_spec('niah_multikey', 1, 0.5, corpus_text(), 20260917, "
                "8000, 64); print(s.truths[0], s.distractors[0], s.fixture_id)")
        outputs = {subprocess.run([sys.executable, "-B", "-c", code], cwd=SC_ROOT, capture_output=True,
                                  text=True, timeout=60, check=True,
                                  env={"PYTHONHASHSEED": str(seed), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}).stdout
                   for seed in (1, 2)}
        self.assertEqual(len(outputs), 1)
        local = tasks.build_spec("niah_multikey", 1, 0.5, corpus_text(), 20260917, 8000, 64)
        self.assertEqual(outputs.pop().split(), [local.truths[0], local.distractors[0], local.fixture_id])

    def test_the_rng_is_seeded_with_the_reference_coordinate_string(self):
        # The reference implementation seeds random.Random with this exact string, so the same
        # seed plants the same values in both; string seeding never uses the salted hash().
        self.assertEqual(tasks.probe_seed(20260917, 8000, "niah_single", 0.5, 1),
                         "20260917|8000|niah_single|0.50|1")
        self.assertEqual(tasks.probe_seed(7, 8000, "vt", None, 0), "7|8000|vt|-|0")
        expected = random.Random()
        expected.seed("20260917|8000|niah_single|0.50|1")
        self.assertEqual(tasks.probe_rng(20260917, 8000, "niah_single", 0.5, 1).random(),
                         expected.random())
        code = inspect.getsource(tasks.probe_rng).split('"""')[-1]
        self.assertNotIn("hash(", code)

    def test_values_are_disjoint_from_the_haystack(self):
        haystack = corpus_text().upper()
        for seed in range(50):
            spec = _spec("niah_multivalue", seed=seed, options={"num_values": 5})
            self.assertTrue(all(v not in haystack for v in spec.truths))
            self.assertEqual(len(set(spec.truths)), 5)

    def test_task_options_are_validated(self):
        self.assertEqual(tasks.validate_task_options("niah_multikey", {"num_distractors": 3}),
                         {"num_distractors": 3})
        for task, options, message in (
            ("niah_multikey", {"num_distractor": 3}, "unknown key"),
            ("niah_multikey", {"num_distractors": 99}, r"in \[1, 9\]"),
            ("vt", {"chain_length": True}, "integer"),
            ("fwe", {"alpha": float("nan")}, "number"),
            ("qa", {"anything": 1}, "accepted: none"),
        ):
            with self.subTest(task=task, options=options), self.assertRaisesRegex(ValueError, message):
                tasks.validate_task_options(task, options)
        with self.assertRaisesRegex(KeyError, "unknown accuracy task"):
            tasks.suite_of("niah_sngle")


class TestProbeCounts(unittest.TestCase):
    def test_depth_swept_tasks_multiply_and_the_rest_do_not(self):
        specs = accuracy.build_probe_specs(_cfg(), 8000)
        counts = Counter(s.task for s in specs)
        self.assertEqual(dict(counts), {"niah_single": 4, "vt": 2, "summary": 2, "fact_sheet": 2})
        self.assertEqual(accuracy.planned_probe_count(_cfg()), len(specs))
        self.assertEqual(len({s.coordinate for s in specs}), len(specs))

    def test_full_default_suites_produce_thirty_two_probes(self):
        args = SimpleNamespace(accuracy=True, accuracy_suites=None, accuracy_tasks=None,
                               accuracy_depths=None, accuracy_samples=None)
        resolved = settings._resolve_accuracy({"suites": ["retrieval", "generation"],
                                               "baseline_profile": "paged_min"}, args, [{"name": "paged_min"}])
        self.assertEqual(accuracy.planned_probe_count(resolved), 32)
        self.assertEqual(len(accuracy.build_probe_specs(resolved, 8000)), 32)

    def test_each_probe_carries_its_own_decode_budget(self):
        by_task = {s.task: s.output_tokens for s in accuracy.build_probe_specs(_cfg(), 8000)}
        self.assertEqual((by_task["niah_single"], by_task["summary"]), (64, 256))


class TestAccuracyConfig(unittest.TestCase):
    PROFILES = [{"name": "paged_min"}, {"name": "mtp_k3"}]

    def _resolve(self, section, **overrides):
        args = SimpleNamespace(accuracy=True, accuracy_suites=None, accuracy_tasks=None,
                               accuracy_depths=None, accuracy_samples=None)
        for key, value in overrides.items():
            setattr(args, key, value)
        return settings._resolve_accuracy(section, args, self.PROFILES)

    def test_off_unless_requested(self):
        args = SimpleNamespace(accuracy=False)
        self.assertIsNone(settings._resolve_accuracy({"nonsense": 1}, args, self.PROFILES))

    def test_rejections(self):
        for section, message in (
            (None, "needs an `accuracy` section"),
            ({"suites": ["retreival"]}, "accuracy.suites"),
            ({"suites": ["retrieval"], "retrieval": {"tasks": ["niah_sngle"]}}, "unknown task"),
            ({"suites": ["retrieval"], "retrieval": {"tasks": ["summary"]}}, "selects no retrieval"),
            ({"suites": ["retrieval"], "retrieval": {"depths": [0.0, 1.5]}}, r"\[0.0, 1.0\]"),
            ({"suites": ["retrieval"], "retrieval": {"samples": 0}}, ">= 1"),
            ({"suites": ["retrieval"], "retrieval": {"options": {"niah_multkey": {}}}}, "not a retrieval task"),
            ({"suites": ["retrieval"], "retrieval": {"options": {"niah_multikey": {"x": 1}}}}, "unknown key"),
            ({"suites": ["retrieval"], "nonsense": 1}, "unknown key"),
            ({"suites": ["generation"], "baseline_profile": "absent"}, "baseline_profile"),
            ({"suites": ["retrieval"], "baseline_profile": "absent"}, "not one of the profiles"),
            ({"suites": ["retrieval"], "seed": 1.5}, "integer"),
        ):
            with self.subTest(section=section), self.assertRaisesRegex(settings.ConfigError, message):
                self._resolve(section)

    def test_cli_filters_apply_across_suites(self):
        resolved = self._resolve({"suites": ["retrieval", "generation"], "baseline_profile": "paged_min"},
                                 accuracy_tasks=["vt", "summary"], accuracy_depths=[0.8, 0.2], accuracy_samples=5)
        self.assertEqual((resolved["retrieval"]["tasks"], resolved["generation"]["tasks"]), (["vt"], ["summary"]))
        self.assertEqual(resolved["retrieval"]["depths"], [0.2, 0.8])
        self.assertEqual(resolved["generation"]["samples"], 5)
        dropped = self._resolve({"suites": ["retrieval", "generation"], "baseline_profile": "paged_min"},
                                accuracy_tasks=["vt"])
        self.assertEqual(dropped["suites"], ["retrieval"])
        with self.assertRaisesRegex(settings.ConfigError, "selects no task"):
            self._resolve({"suites": ["retrieval"]}, accuracy_tasks=["summary"])

    def test_the_baseline_is_optional_for_every_suite(self):
        # As the reference: without a baseline there are no deltas and generation reports
        # only its grounded Coverage column.
        for suites in (["retrieval"], ["generation"], ["retrieval", "generation"]):
            with self.subTest(suites=suites):
                self.assertIsNone(self._resolve({"suites": suites})["baseline_profile"])


# ---------------------------------------------------------------------------
# Ground truth and prompts
# ---------------------------------------------------------------------------
class TestGroundTruthSurvivesTruncation(unittest.TestCase):
    def _counts(self, spec, target):
        prompt, seen = build_probe_prompt(FakeTokenizer(), target, spec.inserts, spec.question, spec.filler)
        self.assertEqual(seen, target)
        body = prompt.split("WORD LIST", 1)[1].split("---")[0]
        return Counter(word for word in body.split() if word.isalpha())

    def test_cwe_and_fwe_top_words_are_the_recorded_truths(self):
        for target in (3000, 9000):
            with self.subTest(target=target):
                cwe = _spec("cwe", options={"num_target_words": 10})
                self.assertEqual({w for w, _ in self._counts(cwe, target).most_common(10)}, set(cwe.truths))
                fwe = _spec("fwe", options={"top_k": 3})
                self.assertEqual([w for w, _ in self._counts(fwe, target).most_common(3)], fwe.truths)

    def test_every_task_lands_on_size_with_inserts_intact(self):
        for task in tasks.KNOWN_TASKS:
            spec = _spec(task)
            prompt, seen = build_probe_prompt(FakeTokenizer(), 4000, spec.inserts, spec.question, spec.filler)
            self.assertEqual(seen, 4000, task)
            for _depth, sentence in spec.inserts:
                self.assertIn(sentence, prompt, task)


# ---------------------------------------------------------------------------
# Scorers
# ---------------------------------------------------------------------------
class TestScorers(unittest.TestCase):
    def test_retrieval_golden_cases(self):
        self.assertTrue(scoring.exact_match("The Code", ["code"]))
        self.assertFalse(scoring.exact_match("the code is 7Q4M91", ["7Q4M91"]))
        self.assertTrue(scoring.exact_match("VAR_A, VAR_B", ["VAR_B", "VAR_A"]))
        self.assertEqual(scoring.string_match_all("codes: AAA", ["AAA", "BBB"]), 0.5)
        self.assertEqual(scoring.string_match_part("It is in March.", ["March", "03"]), 1.0)
        self.assertAlmostEqual(scoring.token_f1("the secret code is 7Q4M91", ["7Q4M91"]), 0.4)
        self.assertEqual(scoring.intersection_over_union(["pencil", "beaker", "comet", "glacier"],
                                                         ["pencil", "beaker"]), 0.5)
        self.assertIsNone(scoring.distractor_rate("anything", []))
        self.assertEqual(scoring.split_items("1. apple, banana and cherry\n- date"),
                         ["apple", "banana", "cherry", "date"])

    def test_article_handling_differs_between_retrieval_and_lexical_scoring(self):
        pred, ref = "the cat sat on a mat", "the cat sat on the mat"
        self.assertEqual(scoring.tokens(pred), scoring.tokens(ref))  # SQuAD drops articles
        self.assertLess(scoring.rouge_n(pred, ref, 1), 1.0)            # lexical keeps them
        self.assertLess(scoring.rouge_l(pred, ref), 1.0)
        self.assertEqual(scoring.intersection_over_union(["the", "beaker"], ["the", "beaker"]), 1.0)

    def test_fidelity_golden_cases(self):
        text = "Energy is conserved; it only changes form."
        self.assertEqual((scoring.rouge_l(text, text), scoring.chrf(text, text)), (1.0, 1.0))
        self.assertEqual(scoring.divergent_tokens([1, 2, 3, 4, 5], [1, 2]),
                         {"fdt": 2, "fdt_norm": 0.4, "sdt": 3, "sdt_norm": 0.6})
        self.assertEqual(scoring.divergent_tokens([], [1])["fdt"], None)
        paraphrase = accuracy.score_fidelity("Energy is always conserved in a closed system.",
                                             "In a closed system, energy is always conserved.")
        self.assertEqual(paraphrase["fdt"], 0)
        self.assertGreater(paraphrase["rouge1"], 0.9)

    def test_dispatch_and_decoys(self):
        cwe = _spec("cwe")
        self.assertLess(accuracy.score_retrieval(", ".join(cwe.truths + ["extra"]), cwe)["recall"], 1.0)
        multikey = _spec("niah_multikey")
        confused = accuracy.score_retrieval(f"the code is {multikey.distractors[0]}", multikey)
        self.assertEqual(confused["recall"], 0.0)
        self.assertGreater(confused["distractor_rate"], 0.0)
        self.assertIsNone(accuracy.score_grounding("x", _spec("summary"))["fact_coverage"])


# ---------------------------------------------------------------------------
# Case scoring and cross-case fidelity
# ---------------------------------------------------------------------------
def _answers(specs, correct, skip=(), prompt_hash="p"):
    rows = []
    for index, spec in enumerate(specs):
        row = {"suite": spec.suite, "task": spec.task, "depth": spec.depth, "sample": spec.sample,
               "fixture_id": spec.fixture_id, "prompt_sha256": f"{prompt_hash}{index}",
               "iteration": index + 1, "warmup": False}
        if index in skip:
            rows.append({**row, "status": "skipped", "skip_reason": "PromptSizeError"})
            continue
        if spec.suite == accuracy.SUITE_GENERATION:
            text = ("Energy transfer was the topic. " + " ".join(spec.truths)) if correct else "Vague."
        else:
            text = ", ".join(spec.truths) if correct else "I could not find it"
        rows.append({**row, "status": "ok", "prediction_text": text})
    return rows


def _case(profile, specs, correct, skip=(), status="ok", prompt_hash="p"):
    rows, summary = accuracy.score_case(_answers(specs, correct, skip, prompt_hash), specs)
    return {"model": "M", "artifact_id": "a", "accuracy_seed": 123, "profile": profile,
            "context_tokens": 8000, "status": status, "mode": "accuracy", "pipeline_mode": "paged",
            "mtp": profile != "paged_min", "num_assistant_tokens": None if profile == "paged_min" else 3,
            "accuracy": summary, "_probes": rows, "_model_dir": None}


def _encoder(_case):
    def encode(text):
        return scoring.lexical_tokens(text)

    encode.unit = "words"
    return encode


class TestCaseScoring(unittest.TestCase):
    def setUp(self):
        self.specs = accuracy.build_probe_specs(_cfg(), 8000)

    def test_skipped_probes_are_counted_but_never_in_a_denominator(self):
        case = _case("paged_min", self.specs, True, skip=(0,))
        retrieval = case["accuracy"][accuracy.SUITE_RETRIEVAL]
        self.assertEqual((retrieval["planned"], retrieval["completed"], retrieval["skipped"]), (6, 5, 1))
        self.assertEqual(retrieval["probe_count"], 5)
        self.assertEqual(retrieval["recall_rate"], 1.0)
        self.assertEqual(retrieval["recall_rate_n"], 5)
        self.assertEqual(retrieval["per_task"]["niah_single"]["skipped"], 1)
        skipped = case["_probes"][0]
        self.assertEqual(skipped["status"], "skipped")
        self.assertNotIn("recall", skipped)

    def test_an_answer_without_a_spec_is_dropped(self):
        stray = _answers(self.specs, True) + [{"suite": "retrieval", "task": "niah_single", "depth": 0.42,
                                               "sample": 99, "status": "ok", "prediction_text": "junk"}]
        rows, _ = accuracy.score_case(stray, self.specs)
        self.assertEqual(len(rows), len(self.specs))

    def test_partial_status_comes_from_coverage(self):
        case = {"mode": "accuracy", "planned_probes": 10, "completed_probes": 9, "load_ok": True,
                "measurement_errors": [], "error": None}
        self.assertEqual(benchmark._status(case), "partial")


class TestFidelityPairing(unittest.TestCase):
    def setUp(self):
        self.specs = accuracy.build_probe_specs(_cfg(), 8000)

    def _fill(self, cases, with_similarity=False, embedding=None):
        notes = accuracy.fill_generation_fidelity(cases, "paged_min", _encoder, embedding, with_similarity)
        accuracy.fill_deltas(cases, "paged_min")
        return notes

    def test_a_baseline_that_completes_last_still_fills_every_case(self):
        drifted = _case("mtp_k3", self.specs, False)
        cases = [drifted]
        self._fill(cases)
        self.assertIsNone(drifted["accuracy"]["generation"]["rouge_l"])
        cases.append(_case("paged_min", self.specs, True))
        self._fill(cases)
        generation = drifted["accuracy"]["generation"]
        self.assertLess(generation["rouge_l"], 1.0)
        self.assertEqual(generation["identical_rate"], 0.0)
        self.assertAlmostEqual(drifted["accuracy"]["retrieval"]["deltas"]["recall_rate_delta"], -1.0)
        first = dict(generation)
        self._fill(cases)
        self.assertEqual(drifted["accuracy"]["generation"], first)  # idempotent

    def test_a_prompt_hash_mismatch_leaves_fidelity_unavailable(self):
        cases = [_case("paged_min", self.specs, True), _case("mtp_k3", self.specs, True, prompt_hash="q")]
        self._fill(cases)
        self.assertIsNone(cases[1]["accuracy"]["generation"]["rouge_l"])
        notes = {p.get("fidelity_note") for p in cases[1]["_probes"] if p["suite"] == "generation"}
        self.assertEqual(notes, {"prompt differs from the baseline's"})

    def test_a_failed_baseline_or_another_context_is_never_a_reference(self):
        failed = [_case("paged_min", self.specs, True, status="crashed"), _case("mtp_k3", self.specs, True)]
        self._fill(failed)
        self.assertIsNone(failed[1]["accuracy"]["generation"]["rouge_l"])
        other = _case("paged_min", self.specs, True)
        other["context_tokens"] = 32000
        cases = [other, _case("mtp_k3", self.specs, True)]
        self._fill(cases)
        self.assertIsNone(cases[1]["accuracy"]["generation"]["rouge_l"])

    def test_the_baseline_self_comparison_is_identical(self):
        cases = [_case("paged_min", self.specs, True)]
        self._fill(cases)
        generation = cases[0]["accuracy"]["generation"]
        self.assertEqual((generation["identical_rate"], generation["fdt_norm"], generation["sdt_norm"]), (1.0, 1.0, 0.0))
        self.assertEqual({p.get("divergence_unit") for p in cases[0]["_probes"] if p["suite"] == "generation"},
                         {"words"})


class TestOptionalWwb(unittest.TestCase):
    def tearDown(self):
        wwb_adapter._EVALUATOR_CACHE.clear()
        for name in ("whowhatbench", "whowhatbench.whowhat_metrics"):
            sys.modules.pop(name, None)

    def _install(self, evaluate):
        wwb_adapter._EVALUATOR_CACHE.clear()
        package, module = types.ModuleType("whowhatbench"), types.ModuleType("whowhatbench.whowhat_metrics")

        class TextSimilarity:
            def __init__(self, model_id):
                import os
                self.offline = os.environ.get("HF_HUB_OFFLINE")

            def evaluate(self, gt, prediction):
                return evaluate(gt, prediction)

        module.TextSimilarity = TextSimilarity
        package.whowhat_metrics = module
        sys.modules.update({"whowhatbench": package, "whowhatbench.whowhat_metrics": module})

    def test_missing_wwb_makes_only_similarity_unavailable(self):
        wwb_adapter._EVALUATOR_CACHE.clear()
        sys.modules["whowhatbench"] = None  # import fails as if absent
        sys.modules["whowhatbench.whowhat_metrics"] = None
        specs = accuracy.build_probe_specs(_cfg(), 8000)
        cases = [_case("paged_min", specs, True), _case("mtp_k3", specs, False)]
        notes = accuracy.fill_generation_fidelity(cases, "paged_min", _encoder,
                                                  wwb_adapter.DEFAULT_EMBEDDING_MODEL, with_similarity=True)
        self.assertTrue(any("not installed" in note for note in notes))
        generation = cases[1]["accuracy"]["generation"]
        self.assertIsNone(generation["similarity"])
        self.assertIsNotNone(generation["rouge_l"])

    def test_return_shapes_and_offline_loading(self):
        self._install(lambda gt, pred: ({"similarity": [0.9]}, {"similarity": [0.95, 0.85]}))
        result = wwb_adapter.similarity(["a", "b"], ["c", "d"])
        self.assertEqual(result.values, [0.95, 0.85])
        self.assertEqual(wwb_adapter._EVALUATOR_CACHE[wwb_adapter.DEFAULT_EMBEDDING_MODEL].offline, "1")
        self._install(lambda gt, pred: [0.1])
        self.assertFalse(wwb_adapter.similarity(["a", "b"], ["c", "d"]).available)
        self._install(lambda gt, pred: object())
        self.assertIn("not one this adapter recognizes", wwb_adapter.similarity(["a"], ["b"]).reason)

        def boom(gt, pred):
            raise RuntimeError("boom")

        self._install(boom)
        self.assertIn("boom", wwb_adapter.similarity(["a"], ["b"]).reason)
        with self.assertRaisesRegex(ValueError, "paired inputs"):
            wwb_adapter.similarity(["a"], ["b", "c"])


class TestSafetyAndTextPolicy(unittest.TestCase):
    def test_generated_text_is_never_executed(self):
        import ast

        for module in (trial_runner, benchmark, accuracy, scoring, report, settings, evidence):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, ("exec", "eval", "compile"), module.__name__)
                    for keyword in node.keywords:
                        if keyword.arg == "shell":
                            self.assertFalse(getattr(keyword.value, "value", False), module.__name__)
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                    self.assertFalse(any(n.split(".")[0] in ("pickle", "marshal") for n in names),
                                     module.__name__)

    def test_answers_and_truth_persist_only_under_record_text(self):
        specs = accuracy.build_probe_specs(_cfg(), 8000)
        case = _case("paged_min", specs, True)
        case["_probes"][1]["output_text"] = "x"
        hidden = evidence.strip_text({"probes": case["_probes"]}, record_text=False)
        flat = str(hidden)
        for field in evidence.TEXT_FIELDS:
            self.assertNotIn(f"'{field}'", flat)
        self.assertIn("recall", flat)
        shown = evidence.strip_text({"probes": case["_probes"]}, record_text=True)
        self.assertIn("prediction", shown["probes"][1])

    def test_probe_detail_prints_text_only_when_recorded(self):
        specs = accuracy.build_probe_specs(_cfg(), 8000)
        case = _case("paged_min", specs, True, skip=(0,))
        exported = {**case, "probes": evidence.strip_text(case["_probes"], False)}
        text = "\n".join(report._probe_detail([exported], record_text=False))
        self.assertNotIn("answer :", text)
        self.assertIn("SKIPPED", text)
        self.assertIn("not recorded", text)
        recorded = "\n".join(report._probe_detail([{**case, "probes": case["_probes"]}], record_text=True))
        self.assertIn("answer :", recorded)

    def test_accuracy_report_sections_show_denominators_and_deltas(self):
        specs = accuracy.build_probe_specs(_cfg(), 8000)
        cases = [_case("paged_min", specs, True), _case("mtp_k3", specs, False, skip=(1,), status="partial")]
        accuracy.fill_generation_fidelity(cases, "paged_min", _encoder)
        accuracy.fill_deltas(cases, "paged_min")
        exported = [{**c, "probes": c["_probes"]} for c in cases]
        text = "\n".join(report._accuracy_section(exported, 8000, {"accuracy": _cfg()}))
        self.assertIn("RETRIEVAL ACCURACY", text)
        self.assertIn("GENERATION FIDELITY", text)
        self.assertIn("| Profile | Pipeline | Speculative |", text)
        self.assertNotIn("skipped", text)
        self.assertIn("-100pp", text)
        self.assertIn("d=0.00", text)
        self.assertIn("Best retrieval: paged_min -- recall 100%", text)
        self.assertIn("compares against itself", text)
        # Partial coverage is reported but not ranked.
        self.assertEqual([c["profile"] for c in report._accuracy_leaderboard(exported)], ["paged_min"])


if __name__ == "__main__":
    unittest.main()
