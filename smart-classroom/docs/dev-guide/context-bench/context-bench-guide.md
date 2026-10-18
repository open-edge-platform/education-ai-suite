<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Context Bench

`components/context_bench/` is an offline, text-only OpenVINO LLM benchmark. It answers, per
model, precision, device, context, task and runtime profile:

1. Can this machine process the context within the configured memory budgets?
2. Which profile (KV precision, stateful vs paged pipeline, scheduler, DFlash speculative
   decoding and its window) has the best measured latency?
3. Optionally (`--accuracy`): how does a profile affect synthetic retrieval accuracy and
   generation fidelity relative to a baseline profile?

It never loads the classroom application, starts services, edits application configuration
or chooses production defaults. It measures individual model calls, not classroom workflow
time. Results are observations on the machine that produced them, not qualification.

## Quick start

Run from `smart-classroom/`. The benchmark uses the backend venv
(`<smart-classroom>/../smartclassroom`) that `setup-smart-classroom.ps1` creates; the
application's `requirements.txt` pins everything it needs. Then:

```powershell
# Plan only: settings, redacted locations, the case grid (c01, c02, ...) and probe counts.
# No inference, downloads or files.
.\components\context_bench\run_benchmark.ps1 --list-profiles

# Smoke test, then a repeated comparison
.\components\context_bench\run_benchmark.ps1 --profiles paged_min dflash_k7 --contexts 8000 --throughput-task math --warmup 0 --iterations 1
.\components\context_bench\run_benchmark.ps1 --profiles paged_min dflash_k7 --contexts 8000 --throughput-task math --warmup 1 --iterations 3 --iteration-gap 0

# Accuracy
.\components\context_bench\run_benchmark.ps1 --profiles paged_min dflash_k7 --contexts 8000 --accuracy --accuracy-tasks niah_single fact_sheet --accuracy-depths 0.5 --accuracy-samples 1
```

The launcher forwards every argument to `python -m components.context_bench.benchmark` using
the venv's Python, resolves a relative `--config` against your current directory, runs from
the Smart Classroom root and returns Python's exit code. With the right interpreter active you
can call the module directly; `--list-profiles` and the tests need neither OpenVINO nor
transformers:

```powershell
python -m unittest discover -s components/tests -p "test_context_bench_*.py"
python -m components.context_bench.benchmark --config components/context_bench/config_qwen3.6_35b.yaml --list-profiles
```

| Exit code | Meaning |
| --- | --- |
| 0 | Valid plan, or a completed run in which every case is `ok` |
| 1 | Failed, partial or unqualified cases (for example a weight-precision label mismatch), or an orchestration/output-write failure |
| 2 | Invalid arguments or configuration, or missing required packages |
| 130 | Ctrl-C, after the child was cleaned up and evidence checkpointed |

## Configurations and artifacts

The benchmark only reads artifacts prepared by the serving workflow
(`start-smart-classroom.ps1`) or an explicit export; it never downloads, exports or repairs
files. Missing files are reported per case as `missing_ir` with a hint.

| Config | Model / precision | Profiles | Default run |
| --- | --- | --- | --- |
| `config_qwen3.6_35b.yaml` (default) | Qwen3.6-35B-A3B INT4, `models/openvino/Qwen3.6-35B-A3B/int4` | `paged_min`, `dflash_k3/5/7/15` (draft `models/openvino/Qwen3.6-35B-A3B-DFlash/int4-lmhead`) | 35 cases: contexts 0 and 8000; `code`, `math`, `chat`, `summary_2s`; 512-token ceiling; 30 s gap. `--accuracy`: 5 cases |
| `config_qwen3.8_27b.yaml` | Qwen3.8-27B INT8 (`--weight-format int4` for INT4), `models/openvino/Qwen3.8-27B/<weight_format>` | `paged_min` (plain only) | 1 case: 8000; `summary_2s`; 64 tokens; no gap. `--accuracy`: 1 case |
| `config_qwen3.5_9b.yaml` | Qwen3.5-9B INT4 (`--weight-format int8` for INT8), `models/openvino/Qwen3.5-9B/<weight_format>` | `paged_min`, `stateful` (plain only) | 4 cases: 8000; `summary_2s`, `classroom_summary`; 1024 tokens; no gap. `--accuracy`: 2 cases |

One config per model: the weight formats differ only in the artifact, so `--weight-format`
selects it (the path is derived) rather than a second, otherwise identical file. The accuracy
sections are identical in all three and match the reference configuration.

### Test steps (c01, c02, ...)

A *case* (test step) is one combination of model, context, task and profile, run in its own
child process: load, warm-up(s), then the measured generations (throughput) or the probes
(`--accuracy`), with memory sampled throughout. Cases are numbered in execution order, which is
row by row: every profile runs a task back to back before the next task starts, so a
baseline and its speculative profiles see the same thermal conditions. IDs are zero-padded to
the plan size, so they sort. The ID appears in the console banner (`[c07 ...]`), in
`results.json` (`plan[*].case_id`, `cases[*].case_id`) and in the `CASES` section, failure lines
and not-run lines of `report.txt`. CLI filters renumber the plan; `--list-profiles` prints the
exact grid, with its IDs, before anything loads.

Each config documents its own steps in its header -- the grids, what every context, task and
profile means, and the accuracy plan -- and a test keeps those grids equal to what the
scripts plan. The default plans:

`config_qwen3.6_35b.yaml` -- 1 warm-up + 3 measured generations per case, up to 512 tokens,
30 s idle before each measured one. `none` is the task prompt alone (the DFlash blog's
setting); `8,000 tokens` is a synthetic classroom transcript followed by the task.

```text
  Context           Task       | paged_min  dflash_k3  dflash_k5  dflash_k7  dflash_k15
  none (task only)  code       | c01        c02        c03        c04        c05
  none (task only)  math       | c06        c07        c08        c09        c10
  none (task only)  chat       | c11        c12        c13        c14        c15
  8,000 tokens      code       | c16        c17        c18        c19        c20
  8,000 tokens      math       | c21        c22        c23        c24        c25
  8,000 tokens      chat       | c26        c27        c28        c29        c30
  8,000 tokens      summary_2s | c31        c32        c33        c34        c35
```

`config_qwen3.8_27b.yaml` -- 1 warm-up + 3 measured generations, up to 64 tokens, back to back.

```text
  Context       Task       | paged_min
  8,000 tokens  summary_2s | c01
```

`config_qwen3.5_9b.yaml` -- 1 warm-up + 3 measured generations, up to 1024 tokens, back to back.

```text
  Context       Task              | paged_min  stateful
  8,000 tokens  summary_2s        | c01        c02
  8,000 tokens  classroom_summary | c03        c04
```

With `--accuracy` the throughput cases are replaced by one accuracy case per profile at every
context with a transcript (context 0 has nowhere to plant a fact): `8,000 tokens | accuracy`,
`c01` ... one per profile (5, 1 and 2 cases). Each runs 1 warm-up and 32 probes: 28 RULER
retrieval probes scored against planted ground truth and 4 generation probes scored against
the baseline profile's answer to the identical prompt.

| Task | What each case decodes |
| --- | --- |
| `code` | A Python module with tests (HumanEval-like); after the transcript, or alone at context 0 |
| `math` | Six worked physics/arithmetic/algebra problems (GSM8K-like); same placement |
| `chat` | Eight open-ended assistant requests (MT-Bench-like); same placement |
| `summary_2s` | A two-sentence summary of the transcript (~45 tokens); transcript contexts only |
| `classroom_summary` | The application's summarizer request, a long Markdown summary; transcript contexts only, and needs about 1024 output tokens to finish |
| accuracy | The probes of the `accuracy` section; no timed iterations, latency and memory come from the probes |

Two selected profiles that resolve to the same configuration (typically `--assistant-tokens K`
over a k-sweep) are refused, since every case would run twice; narrow with `--profiles`.

All use one warm-up and three measured iterations. A model name without a `model_dirs`
entry resolves to `<models_base_path>/<provider>/<name after the last />/<weight_format>`,
the same layout the serving preparation workflow uses.
`--weight-format` changes the label and that derived path, never an explicit `model_dirs`
directory; the IR's actual weight compression (NNCF rt_info) is always reported and a label
mismatch is flagged.

Speculative decoding is benchmarked only where serving supports it: DFlash on
Qwen3.6-35B-A3B INT4 with the z-lab drafter. The Qwen3.8 and Qwen3.5 configs are plain only.

### DFlash artifacts

Start the application once with `models.text_gen.vlm_name: Qwen/Qwen3.6-35B-A3B`,
`weight_format: int4` and `speculative: {mode: auto, method: dflash}`; the serving
preparation then exports the drafter to `models/openvino/Qwen3.6-35B-A3B-DFlash/int4` and
derives `.../int4-lmhead`, the `dflash.model` of the config: the same drafter with its own int4
lm_head, requantized from the target's int8 head, so the runtime no longer reads the full int8
head on every draft pass (2-6% cheaper verification passes in the A/B, acceptance unchanged).
To measure the stock drafter, point `dflash.model` at `.../int4`. DFlash also requires the target IR to carry the model-level
rt_info `hidden_states_decoder_layers` (the current `OpenVINO/Qwen3.6-35B-A3B-int4-ov` export
does). For an older export without it, serving derives
`models/openvino/Qwen3.6-35B-A3B/int4-dflash` (same weights, annotated XML); the benchmark
never modifies the target, so preflight fails with `missing_ir` until `model_dirs` points
there.

## Configuration reference

The YAML is safe-loaded and validated strictly: unknown keys, duplicate keys, booleans used as
integers, non-finite numbers and malformed mappings are errors (exit 2). Precedence is CLI >
YAML > tool default; resolved values are never written back.

| Key | Rules |
| --- | --- |
| `model` | `provider: openvino`, `device` (`CPU`, `GPU`, `GPU.1`), `weight_format`, `models_base_path`, optional `model_dirs` |
| `benchmark.models`, `context_tokens` | Unique names; non-negative integers (0 = standalone task prompt, positive = total rendered input tokens) |
| `output_tokens`, `warmup`, `iterations` | >= 2, >= 0, >= 1. Zero warm-up or one iteration is labelled a smoke test |
| `throughput_task` | One or more of `summary_2s` (default), `classroom_summary`, `code`, `math`, `chat`. Summaries skip context 0 |
| `iteration_gap_sec` | Untimed idle before each measured generation (default 0 = sustained); must be below `timeout_sec` |
| `timeout_sec` | Progress timeout (no event for this long), not a total case limit |
| `max_system_memory_pct`, `gpu_memory_budget_gb` | Host RAM budget (default 80); GPU budget in GiB, required for GPU runs; validated when present but not enforced on CPU |
| `cache_dir`, `output_dir`, `record_text` | Compiled-blob cache (optional), evidence base directory, opt-in persistence of synthetic answers (default false) |
| `profiles[]` | `name`, `ov`, `scheduler`, optional `dflash`; any other key (e.g. `mtp`, which is not supported) is an error |
| `profile.scheduler` | Empty = stateful pipeline. Any key = paged, which requires positive `max_num_batched_tokens`, `max_num_seqs` and `enable_prefix_caching: false`. `cache_size`: omitted (runtime-managed), whole GiB, or `auto` |
| `profile.dflash` | `model` (local draft IR directory), `num_assistant_tokens` >= 1, optional `device` (must equal the target device), `enabled`; needs a paged `scheduler`, and `num_linear_attention_blocks >= max_num_seqs + k + 1` when set |
| `accuracy` | Read only with `--accuracy`: `suites`, `baseline_profile` (optional; when set it must be one of the profiles being run -- without it there are no deltas and the generation suite reports only Coverage), `seed`, `embedding_model`, and per-suite `tasks`, `depths`, `samples`, `output_tokens`, `options` |
| `speculative_reference` | Published figures printed beside the window sweep; never ranked |

Overrides: `--pipeline-config KEY=VALUE` (strings into `ov`), `--scheduler-config KEY=VALUE`
(booleans/numbers converted), `KEY=` removes a key; validation runs afterwards and a pipeline
change is announced (moving a stateful profile to paged needs all three required scheduler keys). `--assistant-tokens K` changes only profiles that already
speculate. A requested speculative case either runs that mechanism or fails; it never falls
back to plain generation.

`classroom_summary` is the only task that reads application settings: it safe-loads
`config.yaml` for `app.language` and `models.summarizer.mode`, resolves the template with
`load_prompt("summarizer", language, mode)`, renders with thinking disabled and applies
`/no_think` exactly where the application's renderer does. Content is synthetic; an
unresolvable template is a configuration error. Its answer needs about 1024 output tokens:
the Qwen3.5-9B config sets that ceiling, and the Qwen3.6 default run leaves the task out (as
the reference does) -- run it there with
`--throughput-task classroom_summary --output-tokens 1024`.

### Cache pools

The preflight estimate covers growing KV for full-attention layers (top-level or
`text_config`), context plus decode ceiling (plus `k + 1` verification tokens), fixed
linear-attention state times reserved rows, and the DFlash draft's KV. Any unknown
part makes the estimate unavailable (context 0 always is). A fixed pool below the estimate is
a case error. `auto` becomes `ceil(max(2, 1.3 x estimate))` and must fit
`floor(budget - weights - 8)`; an infeasible or unknown `auto`, `auto` on CPU, and `auto` on
DFlash (no qualified factor) are case errors. The pool is never clamped and `auto` is never
silently removed.

## How a run works

Cases run serially, each in a fresh `spawn` child that loads the local tokenizer
(`local_files_only`, no remote code) and pipeline once. Throughput builds one exactly sized
prompt (configured, HF and OpenVINO counts must agree) and reuses it for the warm-up (full
ceiling) and measured iterations, each with a fresh greedy request. Accuracy runs one prompt and
decode budget per probe (16-token size tolerance); an unbuildable probe becomes a skipped
record, listed in `PROBE DETAIL` and accounted for: as in the reference it does not demote
the case, and the rates are over the scored probes. Before each generate the parent opens a memory window and acknowledges `ready`; after
each record it closes the window, checkpoints and acknowledges `recorded`. A timeout (no
progress), crash or Ctrl-C terminates only the owned child, escalates to kill, and refuses
further cases if death cannot be confirmed. Scoring runs in the parent after the child exits;
optional who_what_benchmark similarity is filled at every report render, as in the reference,
so an interrupted run still reports it for the cases it finished; the embedding model loads
offline (a missing package or model makes only that column unavailable).

## Evidence

Each run creates `<output_dir>/<UTC-timestamp>-<suffix>/` (output directories are gitignored)
with:

- `results.json` -- authoritative, `schema_version: 1`: run ID and revision, tool commit,
  times, completion, redacted resolved settings and source-config hash, environment and
  package versions, artifact identities (XML/JSON hashes, weight sizes), plan with case
  states, counts, warnings, and per case the effective settings, cache provenance, status and
  flags, structured error (category, stage, milestone, phase), raw iteration/probe records
  with per-field timing sources and memory windows, aggregates and accuracy summaries.
- `report.txt` -- rendered from the same snapshot: run header, `CASES` (the plan grid by
  case ID), `SPEED AND RESOURCES`,
  `SPECULATIVE WINDOW SWEEP`, `RETRIEVAL ACCURACY`, `GENERATION FIDELITY`, `PROBE DETAIL`,
  and failures/partial coverage/warnings.

Both are replaced atomically before trials, after every record and case, and in `finally`.
Paths inside the Smart Classroom root are shown relative to it; anything else as
`external:<id>`. Generated and planted text is persisted only with `record_text: true`.

### Reading results

- Latency in ms, durations in s, throughput in tokens/s, memory in GiB. Unavailable values are
  `--` / null, never zero.
- TPOT excludes the first token; `latency` includes prefill; `e2e_throughput` counts input
  and output tokens. Aggregates are p50 with mean, nearest-rank p95, min/max; fewer than 20
  samples carry a small-sample note. Decode tok/s is 1000 / median TPOT.
- AL (acceptance length) excludes the prefill pass; the accepted % is `(AL - 1) / k` and is
  labelled `estimated` when not measured by the runtime. Rank windows by AL against pass cost.
- Speedups compare a speculative case only with a plain case sharing artifact, prompt hash,
  task, device, plan and fully resolved settings; decode, total-call and steady speedups are
  separate, and differing auto pools are marked confounded. Output forks are warnings.
- Memory is system-wide and sampled (default 0.5 s); windows include IPC/sampling delay.

| Status | Meaning |
| --- | --- |
| `ok` | All planned work completed with required telemetry inside budgets |
| `memory_limit`, `gpu_memory_limit` | Completed, but a measured budget was exceeded |
| `measurement_error` | Completed, but required telemetry or integrity (e.g. runtime input count) is missing |
| `partial` | Only some iterations completed, or accuracy probes that were neither scored nor skipped |
| `oom`, `gpu_abort`, `unsupported` | Allocation/scheduler failure, device command abort, unsupported property or capability |
| `timeout`, `crashed` | No progress within `timeout_sec`, or the child died without a result |
| `no_output` | No measured output (warm-up does not count) |
| `load_error`, `error`, `missing_ir` | Other load/generation/preflight/orchestration failure, or absent artifacts |

Only `ok` cases are ranked, and only an `ok` baseline case yields deltas and fidelity.
Accuracy aggregates, deltas and similarity are rounded to 4 decimals, and planted values are
seeded exactly as in the reference implementation, so the same seed plants the same facts.
Synthetic retrieval scores are not published RULER scores, and fidelity measures drift from
the baseline, not absolute quality.
