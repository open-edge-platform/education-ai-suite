# Processing-Time Statistics

Smart Classroom times every run at two levels:

* **Workflow stages**: how long each step of a session took, from start to its
  saved output. Steps include transcription, video analytics (VA), summary and
  mindmap.
* **Model calls**: each individual call to text generation, ASR or OCR. Every
  call records how long it waited for the model, how long it ran, and which
  stage made it.

The two levels are nested: a stage's duration includes its model calls plus
pre- and postprocessing. Use stages to see what a teacher waits for, and model
calls to see what inference costs. The requirements behind this feature are in
[vlm-llm-serving-design.md §7](vlm-llm-serving-design.md#7-processing-time-statistics).

## What Is Recorded

### Stages

| Stage name | Covers | Record |
| --- | --- | --- |
| `transcribe` | Audio input through the final transcript, including waiting for live audio and optional diarization | Stage + ASR calls |
| `va` | Video analytics, from start through final analytics output | Stage only |
| `summarize` | Summary generation through the saved summary (all map/reduce calls when chunking) | Stage + text-generation calls |
| `mindmap` | Mindmap generation, validation and saving | Stage + text-generation calls |
| `segmentation` | Topic segmentation through saved topics | Stage + text-generation calls |
| `report` | Session data collection through the generated report | Stage + text-generation calls |
| `board_ocr` | Board OCR worker during a session | OCR calls only |
| `document_ocr` | `POST /ocr/extract-text` | OCR calls only |
| `qa`, `video_captioning`, `grading` | Content-search Q&A, video captioning and grading requests to `/v1/chat/completions` | Text-generation calls only |
| `chat_api` | Any other `/v1/chat/completions` request | Text-generation calls only |

Stages recorded through calls only have no stage record. The report script
draws them as a span from their first to their last call.

A client of `/v1/chat/completions` can name its stage with the
`X-SC-Stage: <lowercase_name>` header (letters, digits and `_`, up to 32
characters). Otherwise its calls are recorded as `chat_api`.

### Model Calls

Each call to text generation (`text_gen`), ASR (`asr`) or OCR (`ocr`) creates
one record. A record stores the model, precision, device and decoding method
(`plain` or `dflash`), plus these times:

```text
submitted_at ──queue_wait_ms──▶ admitted ──latency_ms──▶ finished
                                    └─first_output_ms─▶ first streamed token
```

* `queue_wait_ms`: time waiting for a free model slot. When the queue is full
  the call is `rejected` and has no latency.
* `latency_ms`: from admission to the end of the call. A streamed call ends when
  its last token is produced, not when the stream is created.
* For text generation, the runtime also reports `ttft_ms`, `tpot_ms`,
  `decode_tps`, `input_tokens` and `output_tokens`. With DFlash it also reports
  `draft_tokens` (tokens drafted) and `accepted_tokens` (tokens accepted).

Records hold timing metadata only. They never contain prompts, transcripts,
images, tool arguments or local paths.

### Not Recorded

* Per-call times inside VA, embedding, reranking and grading layout or detection
  models. VA has a stage record only.
* Model download, conversion, load and warm-up. These appear once per start in
  `GET /health` under `text_gen.serving.startup` (`prepare_s`, `load_s`,
  `warmup_s`).

## Where the Data Goes

| Location | Contents | Lifetime |
| --- | --- | --- |
| `GET /processing-stats` | Statistics computed from the latest 4,000 stage and call records held in memory | Until the backend restarts |
| `<project>/<session>/logs/stage_events.jsonl` | One JSON line per stage attempt | Kept with the session |
| `<project>/<session>/logs/model_calls.jsonl` | One JSON line per model call that belongs to a session | Kept with the session |

`<project>` is the `Project` location and name in `runtime_config.yaml`
(`storage/smart-classroom` by default). Calls that belong to no session, such
as plain chat API requests, are kept only in memory.

## Query the API

```bash
# All records currently in memory
curl http://127.0.0.1:8000/processing-stats

# One session, with the raw records the report script reads
curl "http://127.0.0.1:8000/processing-stats?session_id=20261017-235509-d65d&raw=true" -o stats.json
```

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/processing-stats?session_id=20261017-235509-d65d&raw=true" |
    ConvertTo-Json -Depth 8 | Set-Content stats.json -Encoding utf8
```

The response contains three lists of statistics:

* `stages`: one entry per stage.
* `model_calls_by_stage`: grouped by capability, stage, model, precision,
  device and decoding method.
* `model_calls_by_model`: the same grouping without the stage.

Each metric is a distribution over successful samples. Failed and cancelled
attempts are counted separately. An abridged real response:

```json
{
  "session_id": "20261017-235509-d65d",
  "percentile_method": "nearest-rank on sorted successful samples",
  "units": {"stage": "seconds", "model_call": "milliseconds", "throughput": "tokens/s"},
  "stages": [
    {"stage": "summarize",
     "duration_sec": {"count": 1, "total": 38.141, "mean": 38.141, "min": 38.141,
                      "max": 38.141, "p50": 38.141, "p95": 38.141, "small_sample": true},
     "failed_count": 0, "failed_elapsed": null, "cancelled_count": 0, "cancelled_elapsed": null}
  ],
  "model_calls_by_stage": [
    {"capability": "text_gen", "stage": "summarize", "model": "Qwen/Qwen3.6-35B-A3B",
     "precision": "int4", "device": "GPU", "decoding": "dflash",
     "latency_ms": {"count": 1, "p50": 38094.0, "p95": 38094.0, "...": "..."},
     "ttft_ms": {"count": 1, "p50": 3750.129, "p95": 3750.129, "...": "..."},
     "failed_count": 0, "cancelled_count": 0}
  ]
}
```

With `raw=true` the response also contains `raw.stages` and `raw.model_calls`.

## Generate a Report

[Scripts/processing_stats_report.py](../../Scripts/processing_stats_report.py)
turns the raw records into a Markdown report. Run it from `smart-classroom/Windows/`
with the backend virtual environment active:

```powershell
# One session from its log files (works after a restart)
python Scripts/processing_stats_report.py storage/smart-classroom/20261017-235509-d65d -o report.md

# Several sessions: one timeline each, combined statistics tables
python Scripts/processing_stats_report.py storage/smart-classroom/<session> storage/smart-classroom/<session> -o report.md

# A saved API response (needs raw=true); --session keeps one session
python Scripts/processing_stats_report.py stats.json --session 20261017-235509-d65d -o report.md
```

Without `-o`, the report is printed to the console. For each session it shows:

* **Workflow window**: from the first stage or call to the end of the last one.
  The report also shows how long the remaining outputs took after transcription
  ended.
* **Timeline**: one lane per stage and one per model capability, along a shared
  time axis. The chart is drawn twice: as a Mermaid Gantt chart (rendered by
  GitHub, and by VS Code with a Mermaid preview extension) and as plain text.
  Failed or interrupted work is red in Mermaid and `X` in the text view. Lanes
  marked `*` are drawn from model calls only.
* **Stages**: one row per attempt, with start and end offsets, duration, the
  number of model calls, their total model time (failed and cancelled calls
  included) and their queue wait. A call is counted for the last attempt of its
  stage that started before the call was submitted, so a retried stage does not
  show the same calls twice.

After the per-session sections, the report adds two tables for all sessions:
stage-duration statistics, and model-call statistics. The model-call table
shows latency, queue wait, TTFT, decode throughput, token counts, DFlash
accepted/drafted tokens, and failures.

Plain-text timeline from a real session (Qwen3.6-35B-A3B with DFlash, live
recording):

```text
transcribe      |████████████████████████████████                                |
va              | ██████████████████████████████████████████████████████████     |
board_ocr *     |  ░░░░                                                          |
summarize       |                                ████████                        |
mindmap         |                                       ████████████             |
segmentation *  |                                                          ░░░░░░|
asr calls       |████████████████████████████████                                |
ocr calls       |  ████                                                          |
text_gen calls  |                                ███████████████████       ██████|
                ++---------------+---------------+--------------+---------------++
                 0s             84s            169s           253s            337s
```

In this run, segmentation is marked `*` because the application was closed
before that stage finished: its model call completed, but no stage record was
written.

## Reading the Numbers

* **Do not add up stage durations.** ASR, VA and board OCR run at the same time,
  and summary, mindmap, segmentation and report share one text-generation
  queue. Use the workflow window for end-to-end time.
* **Live recordings include recording time.** `transcribe` and `va` run as long
  as the input does. To measure processing cost, compare the time after
  transcription ended, or replay a fixed recording.
* **Queue wait is not latency.** A slow stage with a high queue wait was waiting
  for another stage's call to finish.
* **Model TTFT is not the time to the first visible text.** `ttft_ms` is measured
  inside the runtime. What the user sees also includes request preparation,
  queueing, transport, and earlier map calls when a summary is chunked.
* **Small samples.** `small_sample: true` (⚠ in the report) means fewer than 20
  samples. A p95 over a single run is an observation, not a distribution.
  Compare repeated warm runs with the same input, settings and enabled stages.
* **DFlash.** Accepted ÷ drafted tokens shows how much of the draft the target
  kept. Compare plain and DFlash runs on the same input and statistic. A run
  that fell back to plain generation reports `decoding: plain`.
* **Unavailable values are `null` (`—` in the report), never zero.**

## Field Reference

**Stage record** (`stage_events.jsonl`, `raw.stages`): `session_id`, `stage`,
`status` (`done`, `failed` or `interrupted`), `started_at` and `ended_at` (UTC,
millisecond precision), `duration_sec`. Records in the session file also carry
`error_class` and `error_detail`.

**Model-call record** (`model_calls.jsonl`, `raw.model_calls`):

| Field | Meaning |
| --- | --- |
| `id`, `session_id`, `stage` | Record identity and attribution |
| `capability`, `model`, `precision`, `device`, `decoding`, `stream` | What ran and how |
| `submitted_at` | UTC time of submission |
| `status`, `error_class` | `ok`, `failed`, `cancelled` (client disconnected) or `rejected` (queue full) |
| `queue_wait_ms`, `latency_ms`, `first_output_ms` | See [Model Calls](#model-calls) |
| `client_cancelled_after_ms` | When the client left, measured from admission. Native inference still running after that is included in `latency_ms`. |
| `ttft_ms`, `tpot_ms`, `decode_tps`, `input_tokens`, `output_tokens`, `runtime_generate_s` | Text-generation metrics reported by the runtime |
| `draft_tokens`, `accepted_tokens` | DFlash draft tokens proposed and accepted |

Durations come from a high-resolution clock in the backend process. Before
this release, durations on Windows were measured in steps of about 15.6 ms,
and stage timestamps had one-second precision. The report script reads both
formats.
