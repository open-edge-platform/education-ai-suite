# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""The accuracy path: which probes a case runs, and what their answers score.

Two suites, because "does this configuration still use the long context correctly" has two
halves that fail independently:

  * **Retrieval** -- RULER-style synthetic probes (`tasks.py`) scored against known ground
    truth: item recall, IoU for aggregation, any-accepted-answer for QA, plus exact match,
    token F1 and the distractor rate.
  * **Generation** -- a real classroom task at a realistic answer length, scored for
    *fidelity* against the baseline profile's answer to the identical prompt: optional
    embedding similarity (`wwb_adapter`), ROUGE/chrF (lexical) and FDT/SDT (token-exact).
    Fidelity measures drift from the baseline, not absolute summary quality.

Scoring runs in the orchestrator after the child has exited and the memory sampler has
stopped, so scoring resources never enter an inference measurement; the child only returns
generated text. Fidelity is cross-case -- the reference is another profile's output -- so it
is (re)computed idempotently over the whole result set, pairing probes by model/artifact,
context, seed, coordinate, fixture identity and prompt hash, independent of case order.

Skipped probes (prompt-build failures) are explicit records: they count toward the planned
total, never toward a score denominator.
"""

from __future__ import annotations

from components.context_bench import scoring, tasks, wwb_adapter
from components.context_bench.context_builder import corpus_text
from components.context_bench.tasks import (  # re-exported for benchmark.py and tests
    SUITE_GENERATION,
    SUITE_RETRIEVAL,
    ProbeSpec,
)

__all__ = [
    "SUITE_GENERATION", "SUITE_RETRIEVAL", "ProbeSpec",
    "RETRIEVAL_METRICS", "GENERATION_METRICS", "PROBE_SCORE_FIELDS", "FIDELITY_FIELDS",
    "build_probe_specs", "planned_probe_count", "probe_payload", "score_retrieval",
    "score_grounding", "score_fidelity", "score_case", "fill_generation_fidelity",
    "fill_deltas", "aggregate", "group_aggregate", "delta", "metrics_for",
]

RETRIEVAL_METRICS = ("exact_match_rate", "recall_rate", "token_f1", "distractor_rate")
GENERATION_METRICS = (
    "similarity", "rouge1", "rouge2", "rouge_l", "chrf",
    "fdt", "fdt_norm", "sdt_norm", "identical_rate", "fact_coverage",
)

_AGGREGATE_NAMES = {
    "exact_match": "exact_match_rate",
    "recall": "recall_rate",
    "identical": "identical_rate",
}
_PROBE_FIELD = {aggregate: probe for probe, aggregate in _AGGREGATE_NAMES.items()}

PROBE_SCORE_FIELDS = (
    "exact_match", "recall", "token_f1", "distractor_rate",
    "similarity", "rouge1", "rouge2", "rouge_l", "chrf",
    "fdt", "fdt_norm", "sdt", "sdt_norm", "identical", "fact_coverage",
)

# Cross-case fields, cleared and recomputed on every fill so repeated fills never accumulate.
FIDELITY_FIELDS = (
    "similarity", "rouge1", "rouge2", "rouge_l", "chrf",
    "fdt", "fdt_norm", "sdt", "sdt_norm", "identical", "divergence_unit", "fidelity_note",
)

# Only an `ok` baseline case is a reference for deltas and fidelity, as in the reference
# implementation: a baseline demoted by a budget or measurement rule leaves every delta `--`.
_REFERENCE_STATUSES = ("ok",)


def metrics_for(suite: str) -> tuple:
    return GENERATION_METRICS if suite == SUITE_GENERATION else RETRIEVAL_METRICS


# ---------------------------------------------------------------------------
# Probe construction
# ---------------------------------------------------------------------------
def build_probe_specs(accuracy_cfg: dict, context_tokens: int) -> list:
    """Every probe one (model, profile, context) case runs, in a deterministic order:
    suite, then task, then depth, then sample. Depth-swept tasks produce
    ``depths x samples`` probes; the rest produce ``samples``."""
    haystack = corpus_text()
    seed = accuracy_cfg.get("seed", 0)
    specs = []
    for suite in (SUITE_RETRIEVAL, SUITE_GENERATION):
        section = accuracy_cfg.get(suite)
        if not section:
            continue
        options = section.get("options") or {}
        for task in section["tasks"]:
            depths = section["depths"] if tasks.is_depth_swept(task) else [None]
            for depth in depths:
                for sample in range(section["samples"]):
                    specs.append(tasks.build_spec(
                        task=task,
                        sample=sample,
                        depth=depth,
                        haystack=haystack,
                        seed=seed,
                        context_tokens=context_tokens,
                        output_tokens=section["output_tokens"],
                        options=options.get(task) or {},
                    ))
    return specs


def planned_probe_count(accuracy_cfg: dict) -> int:
    """Probes per accuracy case, computed from the configuration alone (no spec building)."""
    total = 0
    for suite in (SUITE_RETRIEVAL, SUITE_GENERATION):
        section = (accuracy_cfg or {}).get(suite)
        if not section:
            continue
        total += sum(
            tasks.probe_count(task, section["samples"], section["depths"])
            for task in section["tasks"]
        )
    return total


def probe_payload(spec: ProbeSpec, index: int) -> dict:
    """The serializable part of a spec the child needs to build and generate one probe."""
    return {
        "probe_index": index,
        "suite": spec.suite,
        "task": spec.task,
        "sample": spec.sample,
        "depth": spec.depth,
        "inserts": [list(pair) for pair in spec.inserts],
        "question": spec.question,
        "filler": spec.filler,
        "output_tokens": spec.output_tokens,
        "fixture_id": spec.fixture_id,
    }


# ---------------------------------------------------------------------------
# Scoring one answer
# ---------------------------------------------------------------------------
def score_retrieval(prediction: str, spec: ProbeSpec) -> dict:
    """Retrieval scores for one answer. `recall` is the task's own RULER scorer; exact match
    and token F1 are the SQuAD pair; `distractor_rate` is the precision signal."""
    if spec.scorer == tasks.SCORER_IOU:
        recall = scoring.intersection_over_union(scoring.split_items(prediction), spec.truths)
    elif spec.scorer == tasks.SCORER_MATCH_PART:
        recall = scoring.string_match_part(prediction, spec.truths)
    else:
        recall = scoring.string_match_all(prediction, spec.truths)
    return {
        "exact_match": scoring.exact_match(prediction, spec.truths),
        "recall": recall,
        "token_f1": scoring.token_f1(prediction, spec.truths),
        "distractor_rate": scoring.distractor_rate(prediction, spec.distractors),
    }


def score_grounding(prediction: str, spec: ProbeSpec) -> dict:
    """The generation suite's ground-truth score: share of planted facts the answer names.
    None for the open-ended `summary` task, which has no ground truth by design."""
    if not spec.truths:
        return {"fact_coverage": None}
    return {"fact_coverage": scoring.string_match_all(prediction, spec.truths)}


def score_fidelity(prediction: str, reference: str,
                   prediction_ids: list | None = None,
                   reference_ids: list | None = None) -> dict:
    """How far one answer drifted from the baseline's answer to the same prompt.

    `*_ids` are the answers as model token sequences, the unit FDT/SDT are defined over.
    Without them the fallback is lexical words, and the caller labels the unit; the two
    units are never compared with each other.
    """
    if prediction_ids is None:
        prediction_ids = scoring.lexical_tokens(prediction)
    if reference_ids is None:
        reference_ids = scoring.lexical_tokens(reference)
    return {
        "rouge1": scoring.rouge_n(prediction, reference, 1),
        "rouge2": scoring.rouge_n(prediction, reference, 2),
        "rouge_l": scoring.rouge_l(prediction, reference),
        "chrf": scoring.chrf(prediction, reference),
        "identical": prediction == reference,
        **scoring.divergent_tokens(reference_ids, prediction_ids),
    }


def _depth_label(depth) -> str:
    return "-" if depth is None else f"{float(depth):.2f}"


def probe_key(probe: dict) -> tuple:
    return (probe.get("task"), _depth_label(probe.get("depth")), probe.get("sample"))


def score_case(probes: list, specs: list) -> tuple:
    """Score each returned probe against its spec and aggregate per suite.

    Returns ``(rows, summary)``. `rows` are the probe records with ground truth, prediction,
    status and every self-contained score merged in; skipped probes stay as explicit rows
    without scores. `summary` is suite-keyed: overall rates over completed probes, per-task
    and per-depth breakdowns, and planned/completed/skipped counts. Generation fidelity is
    cross-case and is filled later by `fill_generation_fidelity`.
    """
    by_coord = {s.coordinate: s for s in specs}
    rows = []
    for probe in probes:
        spec = by_coord.get(probe_key(probe))
        if spec is None:
            continue
        status = probe.get("status", "ok")
        row = {
            **probe,
            "suite": spec.suite,
            "task": spec.task,
            "status": status,
            "fixture_id": spec.fixture_id,
            "truth": " | ".join(spec.truths),
            "distractors": " | ".join(spec.distractors),
            "scoring_version": scoring.SCORING_VERSION,
        }
        if status == "ok":
            prediction = probe.get("prediction_text") or ""
            row["prediction"] = prediction
            row.update(
                score_grounding(prediction, spec) if spec.suite == SUITE_GENERATION
                else score_retrieval(prediction, spec)
            )
        rows.append(row)

    planned = {}
    for spec in specs:
        planned.setdefault(spec.suite, []).append(spec)
    # Only suites with at least one scored probe get a summary, as in the reference: a case
    # that produced nothing for a suite is absent from that suite's tables, not a row of `--`.
    summary = {
        suite: summarize_suite(suite, [r for r in rows if r["suite"] == suite], suite_specs)
        for suite, suite_specs in planned.items()
        if any(r["suite"] == suite and r["status"] == "ok" for r in rows)
    }
    return rows, summary


def summarize_suite(suite: str, rows: list, specs: list | None = None) -> dict:
    """One suite's overall / per-task / per-depth aggregates with explicit denominators."""
    fields = metrics_for(suite)
    completed = [r for r in rows if r.get("status", "ok") == "ok"]
    summary = aggregate(completed, fields)
    planned = len(specs) if specs is not None else len(rows)
    summary.update({
        "planned": planned,
        "completed": len(completed),
        "skipped": sum(1 for r in rows if r.get("status") == "skipped"),
        "missing": max(0, planned - len(rows)),
    })
    summary["per_task"] = group_aggregate(completed, fields, lambda r: r["task"])
    for task, entry in summary["per_task"].items():
        task_rows = [r for r in rows if r["task"] == task]
        entry["skipped"] = sum(1 for r in task_rows if r.get("status") == "skipped")
        entry["planned"] = (sum(1 for s in specs if s.task == task) if specs is not None
                            else len(task_rows))
    swept = [r for r in completed if tasks.is_depth_swept(r["task"])]
    summary["per_depth"] = group_aggregate(swept, fields, lambda r: _depth_label(r.get("depth")))
    return summary


# ---------------------------------------------------------------------------
# Cross-case fidelity
# ---------------------------------------------------------------------------
def _group_key(case: dict) -> tuple:
    return (case.get("model"), case.get("artifact_id"), case.get("context_tokens"),
            case.get("accuracy_seed"))


def _baseline_for(group: list, baseline_profile: str | None):
    if not baseline_profile:
        return None
    return next(
        (c for c in group if c.get("profile") == baseline_profile
         and c.get("status") in _REFERENCE_STATUSES and c.get("_probes")),
        None,
    )


def _accuracy_groups(cases: list) -> dict:
    groups: dict = {}
    for case in cases:
        if case.get("accuracy"):
            groups.setdefault(_group_key(case), []).append(case)
    return groups


def fill_generation_fidelity(cases: list, baseline_profile: str | None, encoder_for,
                             embedding_model: str | None = None,
                             with_similarity: bool = False) -> list:
    """Score every generation probe against the baseline profile's answer to the same prompt.

    Idempotent: fidelity fields are cleared and recomputed each call, so the result does not
    depend on case order and a baseline that completes last still fills every earlier case.
    A probe pairs only when coordinate, fixture identity and prompt hash all match; a missing
    or failed baseline leaves fidelity unavailable. `encoder_for(case)` returns a
    ``text -> ids`` function with a `unit` attribute. Similarity runs only when
    `with_similarity`, which the benchmark passes on every report render, as the reference
    does. Returns notes for the report.
    """
    notes = []
    for group in _accuracy_groups(cases).values():
        for case in group:
            for probe in case.get("_probes", []):
                if probe.get("suite") == SUITE_GENERATION:
                    for name in FIDELITY_FIELDS:
                        probe.pop(name, None)

        baseline = _baseline_for(group, baseline_profile)
        references = {}
        if baseline is not None:
            references = {
                probe_key(p): p for p in baseline.get("_probes", [])
                if p.get("suite") == SUITE_GENERATION and p.get("status", "ok") == "ok"
            }
        encode = encoder_for(baseline) if references else None

        for case in group:
            paired, paired_refs = [], []
            for probe in case.get("_probes", []):
                if probe.get("suite") != SUITE_GENERATION or probe.get("status", "ok") != "ok":
                    continue
                reference = references.get(probe_key(probe))
                if reference is None:
                    probe["fidelity_note"] = (
                        "no baseline answer" if baseline_profile else "no baseline profile"
                    )
                    continue
                if (reference.get("fixture_id") != probe.get("fixture_id")
                        or reference.get("prompt_sha256") != probe.get("prompt_sha256")):
                    probe["fidelity_note"] = "prompt differs from the baseline's"
                    continue
                prediction = probe.get("prediction") or ""
                reference_text = reference.get("prediction") or ""
                probe.update(score_fidelity(
                    prediction, reference_text,
                    prediction_ids=encode(prediction), reference_ids=encode(reference_text),
                ))
                probe["divergence_unit"] = encode.unit
                paired.append(probe)
                paired_refs.append(reference_text)
            if paired and with_similarity:
                if embedding_model:
                    result = fill_similarity(paired, paired_refs, embedding_model)
                    if not result.available:
                        notes.append(result.reason)
                else:
                    notes.append(
                        "accuracy.embedding_model is null, so the semantic column was switched "
                        "off deliberately. The lexical (ROUGE/chrF) and token-exact (FDT/SDT) "
                        "fidelity columns are unaffected."
                    )
            elif paired and embedding_model:
                notes.append("similarity is scored after all inference cases finish")
            _resummarize_generation(case)
    return sorted(set(notes))


def fill_similarity(probes: list, references: list, model_id: str):
    """Attach WWB's embedding similarity to each probe in one batched call. Probes are left
    untouched when WWB is unavailable: an unmeasured similarity is not a similarity of 0."""
    result = wwb_adapter.similarity(references, [p.get("prediction", "") for p in probes],
                                    model_id)
    if result.available:
        for probe, value in zip(probes, result.values):
            probe["similarity"] = round(float(value), 4)
    return result


def _resummarize_generation(case: dict) -> None:
    """Rebuild the generation suite's aggregates once fidelity columns changed."""
    summary = (case.get("accuracy") or {}).get(SUITE_GENERATION)
    if summary is None:
        return
    rows = [p for p in case.get("_probes", []) if p.get("suite") == SUITE_GENERATION]
    rebuilt = summarize_suite(SUITE_GENERATION, rows)
    # Planned counts come from the probe specs, which only the first summary saw. Deltas
    # are recomputed by fill_deltas after every fidelity pass.
    rebuilt["planned"] = summary.get("planned", rebuilt["planned"])
    rebuilt["missing"] = max(0, rebuilt["planned"] - len(rows))
    for task, entry in rebuilt["per_task"].items():
        entry["planned"] = (summary.get("per_task") or {}).get(task, {}).get(
            "planned", entry["planned"])
    case["accuracy"][SUITE_GENERATION] = rebuilt


def fill_deltas(cases: list, baseline_profile: str | None) -> None:
    """Attach each suite's signed per-metric delta against the baseline profile's case."""
    for group in _accuracy_groups(cases).values():
        for case in group:
            for suite in (SUITE_RETRIEVAL, SUITE_GENERATION):
                (case["accuracy"].get(suite) or {}).pop("deltas", None)
        baseline = _baseline_for(group, baseline_profile)
        if baseline is None:
            continue
        for case in group:
            for suite in (SUITE_RETRIEVAL, SUITE_GENERATION):
                summary = case["accuracy"].get(suite)
                base = baseline["accuracy"].get(suite)
                if summary and base:
                    summary["deltas"] = delta(summary, base, metrics_for(suite))


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def aggregate(scores: list, metrics: tuple) -> dict:
    """Mean of each metric over a set of scored probes, skipping probes it does not apply to.

    Empty input reports a `probe_count` of 0 with no rates rather than phantom zeros.
    """
    out = {"probe_count": len(scores)}
    for metric in metrics:
        field = _PROBE_FIELD.get(metric, metric)
        values = [s[field] for s in scores if isinstance(s.get(field), (int, float, bool))]
        out[metric] = round(sum(float(v) for v in values) / len(values), 4) if values else None
        out[f"{metric}_n"] = len(values)
    return out


def group_aggregate(scored: list, metrics: tuple, key) -> dict:
    """`aggregate` applied per group, keyed by `key(probe)` and sorted by that key."""
    groups: dict = {}
    for probe in scored:
        groups.setdefault(key(probe), []).append(probe)
    return {name: aggregate(rows, metrics) for name, rows in sorted(groups.items())}


def delta(profile_agg: dict, baseline_agg: dict, metrics: tuple) -> dict:
    """Each metric minus the baseline profile's, so a regression reads as negative.

    `distractor_rate` and `sdt_norm` are lower-is-better; the report labels them rather than
    flipping their sign here. None where either side lacks the metric.
    """
    out = {}
    for metric in metrics:
        mine, base = profile_agg.get(metric), baseline_agg.get(metric)
        out[f"{metric}_delta"] = (
            round(mine - base, 4)
            if isinstance(mine, (int, float)) and isinstance(base, (int, float))
            else None
        )
    return out
