# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""Synthetic classroom-transcript prompts sized to an exact token count.

Builds a chat prompt whose *complete rendered* token count -- native chat template, task
overhead and generation prefix included -- matches the configured context, or fails
explicitly when the tokenizer cannot converge. Prompt construction happens before the
measured generation and the final prompt is reused across iterations.

Model-agnostic: only a HuggingFace-style tokenizer (``encode`` / ``decode`` /
``apply_chat_template``) is needed, so everything here is testable with a stub tokenizer.
The transcript content is irrelevant to the measurement -- only the token volume matters --
but varied dialog keeps the tokenizer's merge behaviour representative of a real transcript.
Each candidate prompt is rendered through the chat template exactly once; the rendered text
is never fed back into another template.
"""

from __future__ import annotations

from typing import Protocol


class Tokenizer(Protocol):
    def encode(self, text: str, add_special_tokens: bool = True) -> list:
        ...

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        ...

    def apply_chat_template(self, messages, tokenize: bool = False, **kwargs) -> str:
        ...


class PromptSizeError(ValueError):
    """The requested context cannot be built at the required size."""


SYSTEM_PROMPT = (
    "You are a teaching assistant validating a classroom transcript. Follow the "
    "task after the transcript and answer with useful natural language."
)

_USER_PREFIX = "CLASSROOM TRANSCRIPT\n---\n"
_USER_SUFFIX = (
    "\n---\nTASK\nSummarize the lesson's main topic and one key relationship "
    "explained by the teacher in two concise sentences."
)

# Exact-size correction passes for throughput prompts. Deterministic tokenizers converge in
# one or two; the bound turns a tokenizer that orbits the target into an explicit failure.
MAX_CORRECTION_PASSES = 5

# Chat-template switches every benchmark prompt is rendered with: a generation prefix, and
# reasoning off so the measured decode is the answer rather than a thinking trace.
TEMPLATE_KWARGS = {"add_generation_prompt": True, "enable_thinking": False}

_CORPUS_LINES = [
    "TEACHER: Let's begin today's lesson by reviewing what we covered last week about energy transfer.",
    "STUDENT_01: Could you explain again why kinetic energy depends on the square of the velocity?",
    "TEACHER: Good question. When we double the speed, the energy increases by a factor of four.",
    "STUDENT_02: So a car moving twice as fast needs four times the braking distance?",
    "TEACHER: Precisely, and that is why speed limits matter so much for road safety.",
    "STUDENT_03: What happens to that energy when the car finally stops?",
    "TEACHER: Most of it is converted into heat through friction in the brakes and the tyres.",
    "STUDENT_01: Does that mean energy is never actually lost, only transformed?",
    "TEACHER: Correct, that is the principle of conservation of energy in a closed system.",
    "STUDENT_04: Can you give an everyday example where potential energy becomes kinetic energy?",
    "TEACHER: Think of a roller coaster climbing to the top of a hill and then racing down.",
    "STUDENT_02: At the very top it has the most potential energy and almost no motion.",
    "TEACHER: Exactly, and at the bottom that potential energy has become kinetic energy.",
    "STUDENT_03: How do engineers account for friction and air resistance in real designs?",
    "TEACHER: They add safety margins and measure the losses experimentally in testing.",
    "STUDENT_04: Is there a formula that ties all of these ideas together for the exam?",
    "TEACHER: Yes, we will derive the work-energy theorem step by step on the board now.",
    "STUDENT_01: Should we memorise the derivation or just the final expression?",
    "TEACHER: Understand the derivation; the final expression will follow naturally from it.",
    "STUDENT_02: Thank you, that makes the relationship between force and distance much clearer.",
]


def corpus_text() -> str:
    """The built-in classroom-dialog haystack, as one text block.

    Public so the accuracy path can check a planted value is disjoint from it -- a value
    that happened to be a substring here would score a false retrieval hit.
    """
    return "\n".join(_CORPUS_LINES) + "\n"


def build_text_of_token_length(tokenizer: Tokenizer, target_tokens: int,
                               corpus: str | None = None) -> str:
    """Synthetic transcript text of about ``target_tokens`` tokens.

    Only "about": decoding a sliced id list can re-merge at the seams, so the exact figure
    is whatever the *rendered prompt* measures; `build_benchmark_prompt` owns that
    measurement and corrects against it.

    `corpus` replaces the classroom dialog for the aggregation tasks (`cwe`/`fwe`), whose
    context *is* the data being counted. Their word lists carry the intended frequency ratio
    within one repetition, so slicing the repeated text cannot reorder the answer.
    """
    if target_tokens <= 0:
        return ""

    corpus = corpus or corpus_text()
    corpus_ids = tokenizer.encode(corpus, add_special_tokens=False)
    if not corpus_ids:
        raise PromptSizeError("Tokenizer produced no tokens for the filler corpus.")

    reps = (target_tokens // len(corpus_ids)) + 1
    ids = tokenizer.encode(corpus * reps, add_special_tokens=False)[:target_tokens]
    return tokenizer.decode(ids, skip_special_tokens=True)


def render_prompt(tokenizer: Tokenizer, transcript: str, suffix: str = _USER_SUFFIX,
                  system_prompt: str = SYSTEM_PROMPT, user_prefix: str = _USER_PREFIX,
                  **template_kwargs) -> tuple:
    """Render the benchmark chat prompt around ``transcript`` and measure it.

    Returns ``(prompt_text, prompt_tokens)``; the count includes the chat template and
    special tokens -- the real prefill size. An empty transcript prices the scaffolding.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prefix + transcript + suffix},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, **template_kwargs)
    return prompt, len(tokenizer.encode(prompt))


def build_benchmark_prompt(tokenizer: Tokenizer, target_tokens: int,
                           task: dict | None = None) -> tuple:
    """Build a rendered chat prompt whose token length is exactly ``target_tokens``.

    `task` replaces the framing around the transcript -- any of `system_prompt`,
    `user_prefix` and `suffix` (see `render_prompt`). None keeps the built-in two-sentence
    summary.

    ``target_tokens == 0`` means *no transcript*: the task's `standalone` framing is rendered
    as-is and its own length returned. Only tasks with a standalone framing can do this.

    Returns ``(prompt_text, prompt_tokens)``. Raises `PromptSizeError` when the budget is
    smaller than the scaffolding or exact sizing does not converge within
    `MAX_CORRECTION_PASSES`.
    """
    if target_tokens == 0:
        standalone = (task or {}).get("standalone")
        if not standalone:
            raise PromptSizeError(
                "context_tokens 0 (no transcript) needs a task with a standalone prompt; "
                f"{(task or {}).get('name', 'summary_2s')!r} summarizes the transcript"
            )
        messages = [
            {"role": "system", "content": standalone["system_prompt"]},
            {"role": "user", "content": standalone["user"]},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, **TEMPLATE_KWARGS)
        return prompt, len(tokenizer.encode(prompt))

    template_kwargs = dict(TEMPLATE_KWARGS)
    template_kwargs.update({
        key: value for key, value in (task or {}).items()
        if key in ("system_prompt", "user_prefix", "suffix")
    })

    _, overhead = render_prompt(tokenizer, "", **template_kwargs)
    if target_tokens < overhead:
        raise PromptSizeError(
            f"context_tokens={target_tokens} is smaller than the {overhead}-token prompt "
            "scaffolding (chat template, system prompt and task); raise the context"
        )
    content_target = target_tokens - overhead

    prompt_tokens = None
    for _ in range(MAX_CORRECTION_PASSES):
        prompt, prompt_tokens = render_prompt(
            tokenizer, build_text_of_token_length(tokenizer, content_target), **template_kwargs
        )
        if prompt_tokens == target_tokens:
            return prompt, prompt_tokens
        content_target = max(0, content_target + target_tokens - prompt_tokens)

    raise PromptSizeError(
        f"Could not build an exact {target_tokens}-token prompt in {MAX_CORRECTION_PASSES} "
        f"correction passes; last count was {prompt_tokens}"
    )


# The accuracy path's task framing, mirroring `_USER_SUFFIX`'s "---/TASK" shape so the only
# difference the model sees between a throughput prompt and a probe prompt is the task text.
_PROBE_SUFFIX_TEMPLATE = "\n---\nTASK\n{question}"

_PROBE_CORRECTION_TRIES = 4


def build_probe_prompt(tokenizer: Tokenizer, target_tokens: int, inserts: list,
                       question: str, filler: str | None = None,
                       tolerance: int = 0) -> tuple:
    """A rendered prompt of about ``target_tokens`` with each ``(depth, sentence)`` insert
    planted at its depth (0.0 = top of the transcript, 1.0 = bottom) and ``question`` as
    the task.

    Inserts are sorted by depth and the filler between consecutive depths comes from a
    *cumulative* split, so rounding cannot change the total. Insert bytes are fixed and all
    size correction goes into the filler: planted facts stay intact and at their depths.

    `tolerance` is how many tokens off `target_tokens` the result may land. Each insert adds
    two tokenizer seams, and the correction moves one number (the filler budget) against all
    of that drift, so it can orbit the target indefinitely. A retrieval verdict does not
    depend on one token; the count actually used is returned and recorded. The default 0
    keeps the exact contract.

    `filler` replaces the classroom-dialog haystack for the aggregation tasks. `inserts` may
    be empty for the open-ended generation probe.

    Returns ``(prompt_text, prompt_tokens)``.
    """
    for depth, _sentence in inserts:
        if not 0.0 <= depth <= 1.0:
            raise PromptSizeError(f"insert depth must be in [0.0, 1.0], got {depth}")

    ordered = sorted(inserts, key=lambda pair: pair[0])
    template_kwargs = dict(TEMPLATE_KWARGS)
    suffix = _PROBE_SUFFIX_TEMPLATE.format(question=question)

    _, overhead = render_prompt(tokenizer, "", suffix=suffix, **template_kwargs)
    insert_tokens = sum(
        len(tokenizer.encode("\n" + sentence + "\n", add_special_tokens=False))
        for _depth, sentence in ordered
    )
    if target_tokens + tolerance < overhead + insert_tokens:
        raise PromptSizeError(
            f"context_tokens={target_tokens} cannot hold the {overhead}-token scaffolding plus "
            f"{insert_tokens} token(s) of planted inserts"
        )
    content_target = max(0, target_tokens - overhead)
    best = None

    for _ in range(_PROBE_CORRECTION_TRIES):
        filler_target = max(0, content_target - insert_tokens)
        transcript = _weave(tokenizer, ordered, filler_target, filler)
        prompt, prompt_tokens = render_prompt(
            tokenizer, transcript, suffix=suffix, **template_kwargs
        )
        if abs(prompt_tokens - target_tokens) <= tolerance:
            return prompt, prompt_tokens
        if best is None or abs(prompt_tokens - target_tokens) < abs(best[1] - target_tokens):
            best = (prompt, prompt_tokens)
        content_target = max(insert_tokens, content_target + target_tokens - prompt_tokens)

    raise PromptSizeError(
        f"Could not build a {target_tokens}-token probe prompt with {len(ordered)} insert(s) "
        f"within {tolerance} token(s); closest was {best[1]}. If the target is close to the "
        f"{overhead}-token overhead plus the {insert_tokens}-token insert(s), the context is "
        "too small to place them."
    )


def _weave(tokenizer: Tokenizer, ordered: list, filler_target: int,
           filler: str | None) -> str:
    """Filler and inserts interleaved, with ``filler_target`` tokens of filler in total.

    Segment sizes are differences of rounded *cumulative* positions, so they sum to
    `filler_target` exactly and stay non-negative because the boundaries are sorted.
    """
    boundaries = [0.0] + [depth for depth, _ in ordered] + [1.0]
    cumulative = [round(filler_target * boundary) for boundary in boundaries]
    parts = []
    for index, (_depth, sentence) in enumerate(ordered):
        parts.append(
            build_text_of_token_length(
                tokenizer, cumulative[index + 1] - cumulative[index], filler
            )
        )
        parts.append("\n" + sentence + "\n")
    parts.append(
        build_text_of_token_length(tokenizer, cumulative[-1] - cumulative[-2], filler)
    )
    return "".join(parts)
