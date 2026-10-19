# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""The accuracy task suite: what gets planted in the long context, what is asked about it,
and what counts as the right answer.

**Retrieval** (`SUITE_RETRIEVAL`) follows RULER (Hsieh et al., COLM 2024), which splits
Needle-in-a-Haystack into behaviours a long context can fail at independently:

  * *retrieval* -- `niah_single`, `niah_multikey` (one fact among decoys), `niah_multivalue`
    (every value of one key), `niah_multiquery` (one value of every key)
  * *multi-hop tracing* -- `vt`, chains of variable assignments followed to the end
  * *aggregation* -- `cwe` / `fwe`, which need the whole context counted

plus `qa`, a natural-language question over a planted paragraph.

**Generation** (`SUITE_GENERATION`) is the fidelity family: the model does a real classroom
task at a realistic output length and its answer is compared with the baseline profile's
answer to the identical prompt. `fact_sheet` also carries its own planted ground truth.

Everything is synthetic and seeded from ``(seed, context, task, depth, sample)`` through a
SHA-256 digest, so planted values are identical across processes and runs (Python's salted
``hash()`` is never used). Synthetic retrieval scores are not published RULER dataset scores.

Pure data and strings: this module builds specs, `context_builder` renders them, and
`scoring` grades the answers. Nothing here needs a tokenizer.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field

SUITE_RETRIEVAL = "retrieval"
SUITE_GENERATION = "generation"

# Bumped whenever a builder changes what it plants or asks, so stored fixture identities from
# an older version are never paired with new ones.
FIXTURE_VERSION = 2

# Unambiguous upper-case letters and digits (no O/0 or I/1/l): a scorer never has to decide
# which character the model "meant", and no run of classroom dialog produces one by chance.
VALUE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_VALUE_LENGTH = 6

_KEYS = (
    "access", "session", "registry", "laboratory", "archive",
    "roster", "ledger", "equipment", "library", "workshop",
)

# Real words rather than generated tokens so the tokenizer's merge behaviour over the word
# list stays representative. `cwe` scoring depends on the target:distractor frequency ratio
# within one repetition, not on the vocabulary size.
_VOCABULARY = (
    "lesson quiz teacher student pencil notebook diagram formula energy motion velocity "
    "friction gravity magnet circuit voltage battery lantern compass triangle circle square "
    "fraction decimal integer equation average median pattern sequence measure balance ruler "
    "thermometer beaker funnel crystal mineral fossil planet comet orbit telescope satellite "
    "atmosphere climate rainfall glacier desert forest meadow habitat species mammal reptile "
    "insect blossom pollen harvest granary compost windmill turbine pulley lever wedge screw "
    "hammer anvil forge timber quarry marble granite pottery weaving dyeing pigment canvas "
    "sculpture chorus rhythm melody harmony octave flute drumbeat ballad theatre costume "
    "puppet lantern parchment scroll ledger abacus calendar sundial almanac voyage harbour "
    "anchor cargo lighthouse shoreline estuary current tidepool coral plankton whale dolphin "
    "penguin falcon sparrow beetle spider lizard bison antler burrow thicket canyon plateau "
    "volcano geyser aquifer boulder pebble sediment magnet lantern trellis orchard beehive "
    "silo barn tractor furrow seedling sapling"
).split()
_UNIQUE_VOCABULARY = tuple(dict.fromkeys(_VOCABULARY))

# Targets appear ten times as often as distractors inside every repetition of the generated
# word list, so slicing it to an exact token count moves a count by at most one occurrence
# and cannot reorder the ranking.
_CWE_TARGET_FREQ = 30
_CWE_DISTRACTOR_FREQ = 3

_QA_ITEMS = (
    (
        "Administrative note: the field trip to the {place} observatory is scheduled for "
        "{month}, and it will be led by Doctor {person}.",
        "Which month is the field trip to the observatory scheduled for? "
        "Answer with only the month.",
        "month",
    ),
    (
        "Administrative note: the practical examination will be held in room {place}, and "
        "Doctor {person} is the examiner responsible for it.",
        "Who is the examiner responsible for the practical examination? "
        "Answer with only the name.",
        "person",
    ),
    (
        "Administrative note: the {month} laboratory session on energy transfer takes place "
        "in room {place} under the supervision of Doctor {person}.",
        "Where does the laboratory session on energy transfer take place? "
        "Answer with only the room.",
        "place",
    ),
)
_QA_MONTHS = ("January", "March", "April", "June", "September", "November")
_QA_PLACES = ("Halverson", "Pine Ridge", "Castellane", "Northbrook", "Eastgate")
_QA_PEOPLE = ("Ferreira", "Okonkwo", "Lindqvist", "Nakamura", "Abrahams")

# Several distinct instructions rather than one repeated: a fidelity number from a single
# request says less than one taken across summarize / explain / list / quiz output shapes.
_GENERATION_PROMPTS = (
    "Summarize the lesson's main topic and one key relationship explained by the teacher in "
    "two concise sentences.",
    "Explain, in your own words and in about three sentences, the relationship between speed "
    "and energy as the teacher described it.",
    "List the three most important points a student should revise from this lesson.",
    "Write two short quiz questions a teacher could ask to check understanding of this "
    "lesson, with their answers.",
    "Describe how the teacher moved from the opening review to the final derivation, in two "
    "or three sentences.",
)

# How the answer is graded: RULER's share-of-items-found, its any-acceptable-answer rule for
# paraphrasable questions, and its over-answering-aware metric for aggregation tasks.
SCORER_MATCH_ALL = "match_all"
SCORER_MATCH_PART = "match_part"
SCORER_IOU = "iou"


@dataclass(frozen=True)
class ProbeSpec:
    """One prompt to run and everything needed to grade its answer.

    `inserts` are ``(depth, sentence)`` pairs planted into the synthetic transcript;
    `filler` replaces the dialog haystack for the aggregation tasks. `truths` are the
    acceptable answers and `distractors` the planted decoys that must NOT appear.

    `depth` is None for tasks whose needles are spread by construction (multi-value,
    tracing, aggregation): those get a per-task row instead of a depth sweep.
    `fixture_id` identifies the exact planted content, independent of case order.
    """

    suite: str
    task: str
    sample: int
    question: str
    truths: list = field(default_factory=list)
    distractors: list = field(default_factory=list)
    inserts: list = field(default_factory=list)
    depth: float | None = None
    filler: str | None = None
    scorer: str = SCORER_MATCH_ALL
    output_tokens: int = 32
    fixture_id: str = ""

    @property
    def coordinate(self) -> tuple:
        """The key that pairs an answer back to this spec, and pairs a probe with the
        baseline profile's probe for the same work. Stable across processes and runs."""
        return (self.task, _depth_key(self.depth), self.sample)


def _depth_key(depth) -> str:
    return "-" if depth is None else f"{float(depth):.2f}"


# ---------------------------------------------------------------------------
# Task options
# ---------------------------------------------------------------------------
# Accepted keys per task, as (kind, minimum, maximum). Anything else is a configuration
# error: a typo such as `num_distractor` would otherwise run the defaults as though they had
# been configured.
_VALUE_LENGTH = ("int", 4, 16)
TASK_OPTIONS = {
    "niah_single": {"value_length": _VALUE_LENGTH},
    "niah_multikey": {"num_distractors": ("int", 1, len(_KEYS) - 1),
                      "value_length": _VALUE_LENGTH},
    "niah_multivalue": {"num_values": ("int", 1, 32), "value_length": _VALUE_LENGTH},
    "niah_multiquery": {"num_queries": ("int", 1, len(_KEYS)), "value_length": _VALUE_LENGTH},
    "vt": {"chain_length": ("int", 2, 16), "num_chains": ("int", 1, 16),
           "value_length": _VALUE_LENGTH},
    "cwe": {"num_target_words": ("int", 1, len(_UNIQUE_VOCABULARY) - 1)},
    "fwe": {"top_k": ("int", 1, 20), "alpha": ("float", 0.5, 5.0)},
    "qa": {},
    "summary": {},
    "fact_sheet": {"num_facts": ("int", 1, len(_KEYS)), "value_length": _VALUE_LENGTH},
}


def validate_task_options(task: str, options) -> dict:
    """Validate one task's option mapping; returns a plain copy or raises ValueError."""
    if options is None:
        return {}
    if not isinstance(options, dict):
        raise ValueError(f"options for {task!r} must be a mapping")
    allowed = TASK_OPTIONS.get(task)
    if allowed is None:
        raise ValueError(f"unknown accuracy task {task!r}")
    unknown = sorted(set(options) - set(allowed))
    if unknown:
        accepted = ", ".join(sorted(allowed)) or "none"
        raise ValueError(
            f"options for {task!r} have unknown key(s) {', '.join(map(str, unknown))}; "
            f"accepted: {accepted}"
        )
    resolved = {}
    for key, value in options.items():
        kind, minimum, maximum = allowed[key]
        if kind == "int":
            valid = isinstance(value, int) and not isinstance(value, bool)
        else:
            valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(value))
        if not valid or not minimum <= value <= maximum:
            raise ValueError(
                f"options.{task}.{key} must be {'an integer' if kind == 'int' else 'a number'} "
                f"in [{minimum}, {maximum}], got {value!r}"
            )
        resolved[key] = value
    return resolved


# ---------------------------------------------------------------------------
# Deterministic draws
# ---------------------------------------------------------------------------
def probe_seed(seed: int, context_tokens: int, task: str, depth, sample: int) -> str:
    """The probe's coordinate as the string `probe_rng` seeds from (the reference's key)."""
    return f"{seed}|{context_tokens}|{task}|{_depth_key(depth)}|{sample}"


def probe_rng(seed: int, context_tokens: int, task: str, depth, sample: int) -> random.Random:
    """A generator seeded from the probe's full coordinate, as the reference implementation.

    Every (task, depth, sample) carries different planted values -- a profile cannot score a
    hit by memorizing one answer across the sweep -- while the same config reproduces the
    same run, and the same planted values as a reference run with the same seed. Seeding
    `random.Random` with a string hashes it with SHA-512, never the per-process salted
    `hash()`, so the stream is identical in every process.
    """
    rng = random.Random()
    rng.seed(probe_seed(seed, context_tokens, task, depth, sample))
    return rng


def draw_value(rng: random.Random, haystack: str, length: int = DEFAULT_VALUE_LENGTH) -> str:
    """A high-entropy code that does not occur in `haystack` (checked, not assumed)."""
    upper = haystack.upper()
    for _ in range(1000):
        value = "".join(rng.choice(VALUE_ALPHABET) for _ in range(length))
        if value not in upper:
            return value
    raise ValueError(
        "Could not draw a value disjoint from the haystack; widen VALUE_ALPHABET or raise "
        "the length"
    )


def _draw_distinct(rng: random.Random, haystack: str, count: int, length: int) -> list:
    """`count` distinct values, so two planted facts never share an answer."""
    values: list = []
    while len(values) < count:
        value = draw_value(rng, haystack, length)
        if value not in values:
            values.append(value)
    return values


def _spread(count: int, rng: random.Random) -> list:
    """`count` depths, one per equal band of the transcript, jittered inside its band.

    Even spread rather than random placement: an unlucky uniform draw clustering every
    needle in the last tenth would turn a long-context task into a short-context one.
    """
    if count <= 1:
        return [0.5]
    band = 1.0 / count
    return [
        round(min(1.0, max(0.0, index * band + rng.uniform(0.15, 0.85) * band)), 4)
        for index in range(count)
    ]


def _needle(key: str, value: str) -> str:
    return f"Note for the record: the {key} code for this session is {value}."


# ---------------------------------------------------------------------------
# Retrieval tasks (RULER)
# ---------------------------------------------------------------------------
# Tasks swept across `depths`: they plant one needle whose position is the measured variable.
# The rest place their needles by construction and run `samples` probes at depth None.
DEPTH_SWEPT_TASKS = ("niah_single", "niah_multikey", "qa")


def _build_niah_single(rng, haystack, depth, options) -> dict:
    key = _KEYS[0]
    value = draw_value(rng, haystack, options.get("value_length", DEFAULT_VALUE_LENGTH))
    return {
        "question": (
            f"What is the {key} code mentioned in the transcript? Answer with only the code."
        ),
        "truths": [value],
        "inserts": [(depth, _needle(key, value))],
    }


def _build_niah_multikey(rng, haystack, depth, options) -> dict:
    """The target needle at `depth`, decoys with different keys spread around it.

    A profile losing precision does not stop answering; it answers with the wrong key's
    value, which `distractor_rate` catches where recall alone reads a plain miss.
    """
    count = options.get("num_distractors", 4)
    length = options.get("value_length", DEFAULT_VALUE_LENGTH)
    keys = _KEYS[:count + 1]
    values = _draw_distinct(rng, haystack, len(keys), length)
    inserts = [(depth, _needle(keys[0], values[0]))]
    inserts += [
        (decoy_depth, _needle(key, value))
        for decoy_depth, key, value in zip(_spread(count, rng), keys[1:], values[1:])
    ]
    return {
        "question": (
            f"What is the {keys[0]} code mentioned in the transcript? Several different codes "
            "are recorded; answer with only the one for "
            f"{keys[0]}."
        ),
        "truths": [values[0]],
        "distractors": values[1:],
        "inserts": inserts,
    }


def _build_niah_multivalue(rng, haystack, _depth, options) -> dict:
    """One key, several values, spread through the transcript: every one has to come back."""
    count = options.get("num_values", 4)
    length = options.get("value_length", DEFAULT_VALUE_LENGTH)
    key = _KEYS[0]
    values = _draw_distinct(rng, haystack, count, length)
    return {
        "question": (
            f"The transcript records several {key} codes. List every {key} code it mentions, "
            "separated by commas, and nothing else."
        ),
        "truths": values,
        "inserts": list(zip(_spread(count, rng), (_needle(key, v) for v in values))),
    }


def _build_niah_multiquery(rng, haystack, _depth, options) -> dict:
    """Several keys, one value each: every needle has to be found, not just the easiest."""
    count = options.get("num_queries", 4)
    length = options.get("value_length", DEFAULT_VALUE_LENGTH)
    keys = _KEYS[:count]
    values = _draw_distinct(rng, haystack, len(keys), length)
    listed = ", ".join(keys[:-1]) + f" and {keys[-1]}" if len(keys) > 1 else keys[0]
    return {
        "question": (
            f"The transcript records a code for each of these: {listed}. List all of them, "
            "separated by commas, and nothing else."
        ),
        "truths": values,
        "inserts": list(zip(
            _spread(count, rng), (_needle(k, v) for k, v in zip(keys, values))
        )),
    }


def _build_vt(rng, haystack, _depth, options) -> dict:
    """Variable tracking: chains of assignments that only resolve if every hop is followed."""
    length = options.get("chain_length", 4)
    chains = options.get("num_chains", 4)
    value_length = options.get("value_length", DEFAULT_VALUE_LENGTH)
    chain_values = _draw_distinct(rng, haystack, chains, value_length)
    value = chain_values[0]

    statements, target_names, decoy_names = [], [], []
    for chain in range(chains):
        names = [f"VAR_{chain}_{step}" for step in range(length)]
        statements.append(f"Bookkeeping: {names[0]} is set to {chain_values[chain]}.")
        statements += [
            f"Bookkeeping: {names[step]} is set to the value of {names[step - 1]}."
            for step in range(1, length)
        ]
        (target_names if chain == 0 else decoy_names).extend(names)

    # Interleaved before spreading, so following one chain requires carrying it across the
    # others rather than reading a single block.
    rng.shuffle(statements)
    return {
        "question": (
            f"The transcript assigns values to variables, sometimes by copying another "
            f"variable. List every variable whose final value is {value}, separated by "
            "commas, and nothing else."
        ),
        "truths": target_names,
        "distractors": decoy_names,
        "inserts": list(zip(_spread(len(statements), rng), statements)),
    }


def _build_cwe(rng, _haystack, _depth, options) -> dict:
    """Common word extraction: the context is a word list and the answer its top words."""
    count = options.get("num_target_words", 10)
    vocabulary = list(_UNIQUE_VOCABULARY)
    rng.shuffle(vocabulary)
    targets = vocabulary[:count]
    distractors = vocabulary[count:]

    words = [w for w in targets for _ in range(_CWE_TARGET_FREQ)]
    words += [w for w in distractors for _ in range(_CWE_DISTRACTOR_FREQ)]
    rng.shuffle(words)
    return {
        "question": (
            f"The word list above contains {count} words that occur far more often than any "
            f"other. List those {count} words, separated by commas, and nothing else."
        ),
        "truths": targets,
        "inserts": [],
        "filler": "WORD LIST\n" + " ".join(words) + "\n",
        "scorer": SCORER_IOU,
    }


def _build_fwe(rng, _haystack, _depth, options) -> dict:
    """Frequent word extraction with Zeta-distributed frequencies (harder than `cwe`)."""
    top_k = options.get("top_k", 3)
    alpha = options.get("alpha", 2.0)
    vocabulary = list(_UNIQUE_VOCABULARY)
    rng.shuffle(vocabulary)
    # Rank r appears proportionally to r**-alpha, scaled so the top word survives the filler
    # being sliced to an exact token count.
    counts = [max(1, int(200 * (rank + 1) ** -alpha)) for rank in range(len(vocabulary))]
    words = [w for w, n in zip(vocabulary, counts) for _ in range(n)]
    rng.shuffle(words)
    return {
        "question": (
            f"List the {top_k} words that occur most often in the word list above, most "
            "frequent first, separated by commas, and nothing else."
        ),
        "truths": vocabulary[:top_k],
        "inserts": [],
        "filler": "WORD LIST\n" + " ".join(words) + "\n",
        "scorer": SCORER_IOU,
    }


def _build_qa(rng, _haystack, depth, _options) -> dict:
    """A natural-language question over a planted paragraph; the answer is a normal word."""
    paragraph, question, answer_field = _QA_ITEMS[rng.randrange(len(_QA_ITEMS))]
    fields = {
        "month": _QA_MONTHS[rng.randrange(len(_QA_MONTHS))],
        "place": _QA_PLACES[rng.randrange(len(_QA_PLACES))],
        "person": _QA_PEOPLE[rng.randrange(len(_QA_PEOPLE))],
    }
    return {
        "question": question,
        "truths": [fields[answer_field]],
        "inserts": [(depth, paragraph.format(**fields))],
        "scorer": SCORER_MATCH_PART,
    }


# ---------------------------------------------------------------------------
# Generation tasks (fidelity / lexical task scoring)
# ---------------------------------------------------------------------------
def _build_summary(rng, _haystack, _depth, _options) -> dict:
    """A real classroom task over the transcript; no ground truth by design -- the reference
    is the baseline profile's answer to the same prompt."""
    return {"question": _GENERATION_PROMPTS[rng.randrange(len(_GENERATION_PROMPTS))],
            "truths": [], "inserts": []}


def _build_fact_sheet(rng, haystack, _depth, options) -> dict:
    """Long-form answering with its own ground truth: facts planted, then asked for together."""
    count = options.get("num_facts", 6)
    length = options.get("value_length", DEFAULT_VALUE_LENGTH)
    keys = _KEYS[:count]
    values = _draw_distinct(rng, haystack, len(keys), length)
    return {
        "question": (
            "The transcript records an administrative code for several items. Write a short "
            "report listing each item together with its code, one per line."
        ),
        "truths": values,
        "inserts": list(zip(
            _spread(count, rng), (_needle(k, v) for k, v in zip(keys, values))
        )),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_BUILDERS = {
    "niah_single": (SUITE_RETRIEVAL, _build_niah_single),
    "niah_multikey": (SUITE_RETRIEVAL, _build_niah_multikey),
    "niah_multivalue": (SUITE_RETRIEVAL, _build_niah_multivalue),
    "niah_multiquery": (SUITE_RETRIEVAL, _build_niah_multiquery),
    "vt": (SUITE_RETRIEVAL, _build_vt),
    "cwe": (SUITE_RETRIEVAL, _build_cwe),
    "fwe": (SUITE_RETRIEVAL, _build_fwe),
    "qa": (SUITE_RETRIEVAL, _build_qa),
    "summary": (SUITE_GENERATION, _build_summary),
    "fact_sheet": (SUITE_GENERATION, _build_fact_sheet),
}

RETRIEVAL_TASKS = tuple(n for n, (s, _) in _BUILDERS.items() if s == SUITE_RETRIEVAL)
GENERATION_TASKS = tuple(n for n, (s, _) in _BUILDERS.items() if s == SUITE_GENERATION)
KNOWN_TASKS = RETRIEVAL_TASKS + GENERATION_TASKS


def is_known(task) -> bool:
    return isinstance(task, str) and task in _BUILDERS


def suite_of(task: str) -> str:
    """The suite a task belongs to; raises for an unknown name so a typo is a configuration
    error rather than a silently skipped measurement."""
    if task not in _BUILDERS:
        raise KeyError(
            f"unknown accuracy task {task!r}; known tasks are "
            f"{', '.join(sorted(_BUILDERS))}"
        )
    return _BUILDERS[task][0]


def is_depth_swept(task: str) -> bool:
    """Whether the task is measured across `depths`. See `ProbeSpec.depth`."""
    return task in DEPTH_SWEPT_TASKS


def probe_count(task: str, samples: int, depths: list) -> int:
    """Probes one task contributes per case: ``samples * len(depths)`` if depth-swept."""
    return samples * (len(depths) if is_depth_swept(task) else 1)


def fixture_identity(spec_fields: dict) -> str:
    """SHA-256 over everything a probe plants and asks, with the fixture version."""
    payload = json.dumps(
        {"version": FIXTURE_VERSION, **spec_fields}, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_spec(task: str, sample: int, depth, haystack: str, seed: int,
               context_tokens: int, output_tokens: int, options: dict | None = None) -> ProbeSpec:
    """One probe for `(task, depth, sample)`, deterministic in `seed` and `context_tokens`."""
    suite = suite_of(task)
    options = validate_task_options(task, options or {})
    effective_depth = depth if is_depth_swept(task) else None
    # Seeded with the depth as passed, as the reference: build_probe_specs already passes None
    # for tasks that are not depth-swept.
    rng = probe_rng(seed, context_tokens, task, depth, sample)
    built = _BUILDERS[task][1](rng, haystack, depth, options)
    fields = {
        "suite": suite,
        "task": task,
        "sample": sample,
        "depth": _depth_key(effective_depth),
        "seed": seed,
        "context_tokens": context_tokens,
        "question": built["question"],
        "truths": list(built.get("truths", [])),
        "distractors": list(built.get("distractors", [])),
        "inserts": [[float(d), s] for d, s in built.get("inserts", [])],
        "filler_sha256": (hashlib.sha256(built["filler"].encode("utf-8")).hexdigest()
                          if built.get("filler") else None),
        "scorer": built.get("scorer", SCORER_MATCH_ALL),
        "output_tokens": output_tokens,
    }
    return ProbeSpec(
        suite=suite,
        task=task,
        sample=sample,
        depth=effective_depth,
        output_tokens=output_tokens,
        question=built["question"],
        truths=list(built.get("truths", [])),
        distractors=list(built.get("distractors", [])),
        inserts=list(built.get("inserts", [])),
        filler=built.get("filler"),
        scorer=built.get("scorer", SCORER_MATCH_ALL),
        fixture_id=fixture_identity(fields),
    )
