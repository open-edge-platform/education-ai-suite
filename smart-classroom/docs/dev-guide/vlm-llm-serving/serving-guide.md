<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# VLM/LLM Serving Guide

How to select a text-generation model, enable speculative decoding, prepare
models ahead of time, call tools through port 8000 and read processing-time
statistics. The requirements behind these features are in
[vlm-llm-serving-design.md](vlm-llm-serving-design.md); the offline benchmark is
described in [context-bench-design.md](../context-bench/context-bench-design.md).

> **Qualification status.** The model profiles below are implemented, but
> hardware qualification (the ARL/PTL matrix in the design) and tool-call
> qualification of each profile are still pending. Treat accelerated profiles
> as candidates until their results are published.

## Model Choice

The target is selected as before, under `models.text_gen` in
[config.yaml](../../../config.yaml). Existing selections keep working unchanged.

| `vlm_name` | `weight_format` | Optional accelerator |
| --- | --- | --- |
| `Qwen/Qwen3-VL-8B-Instruct` (default) | `int4`, `int8` | none (plain) |
| `Qwen/Qwen3.5-9B` | `int4`, `int8` | none (plain) |
| `Qwen/Qwen3.6-35B-A3B` | `int4` | `dflash` |
| `Qwen/Qwen3.8-27B` | `int4`, `int8` | none (plain) |

Pre-converted OpenVINO IR is downloaded on first start into
`models/openvino/<model>/<weight_format>`. Other models keep the existing
export path. The catalog lives in
[components/vlm/text_gen_profiles.py](../../../components/vlm/text_gen_profiles.py).

## Speculative Decoding

Add an optional `speculative` block under `models.text_gen`. Omitting it, or
`mode: "off"`, is plain generation and prepares only the target.

```yaml
models:
  text_gen:
    provider: vlm
    vlm_name: Qwen/Qwen3.6-35B-A3B
    device: GPU
    weight_format: int4
    speculative:
      mode: auto          # "off" | auto | "on"
      method: dflash      # auto | dflash | dflash2 | mtp
      draft_source: null  # null | huggingface | local
      draft_model: null
      draft_revision: null
      num_assistant_tokens: null
```

Quote `"off"` and `"on"`: bare `off`/`on` are YAML booleans (they are accepted,
but quoting avoids surprises).

| Setting | Behavior |
| --- | --- |
| `mode: auto` | Accelerate when the profile is qualified and its artifacts prepare and warm up; otherwise plain generation, with the reason in `/health`. |
| `mode: "on"` | Acceleration is required at startup; any reason it cannot run is a startup failure with guidance. |
| `method` | `dflash` is the only method with a profile, for Qwen3.6 INT4; `auto` selects it there. `dflash2` and `mtp` are valid settings without a profile yet: plain generation under `auto`, a startup failure under `"on"`. |
| `draft_source: local` | `draft_model` names an existing OpenVINO IR directory (relative paths resolve from `smart-classroom/`). It is validated, never downloaded or replaced. |
| `draft_revision` | A full 40-character commit. `null` uses the catalog pin (`f181eece646a…` for the Qwen3.6 drafter). |
| `num_assistant_tokens` | Draft window `k`; `null` uses the profile default, 3. Range 1–15. |

Invalid settings (unknown method or key, contradictory source, cross-model
drafter, out-of-range `k`) fail validation at startup in every mode; they never
silently fall back.

While a speculative pipeline is active:

* Requests are greedy. A request with `temperature > 0` is rejected with HTTP 400
  instead of being changed. Classroom stages already generate greedily.
* Image requests run on the same pipeline; image-encoding speedups are not
  claimed.
* If activation fails under `auto`, the server warms a plain pipeline once and
  keeps that decision until the process restarts.

To roll back, remove the block (or set `mode: "off"`) and restart. Prepared
drafter files are kept for later use; superseded ones are moved aside, never
deleted.

### What preparation produces

| Artifact | Location |
| --- | --- |
| Target IR | `models/openvino/<model>/<weight_format>` |
| DFlash drafter source (pinned commit) | `models/hf/<org>__<repo>/<commit>` |
| DFlash drafter IR | `models/openvino/<drafter>/int4` |
| DFlash target with hidden-state metadata | `models/openvino/<model>/<weight_format>-dflash` (only when the stock export lacks `hidden_states_decoder_layers`; weights are hard-linked, the ordinary target is untouched) |
| Manifest | `models/openvino/.manifests/<model>-<weight_format>.json` |

The DFlash drafter is a source checkpoint, downloaded at the catalog's pinned
commit: configuration and weight files only, never repository code. It is
exported with the DFlash classes built into optimum-intel 2.2.0 (installed by
`requirements.txt`), without `--trust-remote-code`; the first start spends a
few minutes on this export. If the export fails, `auto` continues with plain
generation and reports the reason; an IR exported separately can be used with
`draft_source: local`.

## Model Preparation

The backend prepares the configured model when it loads the warm VLM, so
[start-smart-classroom.ps1](../../../start-smart-classroom.ps1), the desktop app
and `python main.py` all prepare the same way, with no extra switch. The first
start downloads or converts what is missing (progress is in the backend log) and
the backend reports ready on `/health` only after warm-up; later starts only
validate. To run offline, start once with network access, or copy the prepared
`models/` directories; the manifest above records what was prepared.

## Tool Calling on Port 8000

`POST /v1/chat/completions` accepts OpenAI function tools on tool-capable
models (the Qwen3/3.5/3.6/3.8 templates render tools). The server returns calls;
**it never executes them** — run, authorize and bound tool loops in your client.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="unused")
tools = [{"type": "function", "function": {
    "name": "get_weather",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                   "required": ["city"]}}}]
messages = [{"role": "user", "content": "Weather in Paris?"}]

first = client.chat.completions.create(model="text_gen", messages=messages, tools=tools)
call = first.choices[0].message.tool_calls[0]          # finish_reason == "tool_calls"
messages += [first.choices[0].message,
             {"role": "tool", "tool_call_id": call.id, "content": '{"temp_c": 21}'}]
answer = client.chat.completions.create(model="text_gen", messages=messages, tools=tools)
```

| Field | Supported |
| --- | --- |
| `tools` | `type: "function"` with `name`, optional `description`, JSON Schema `parameters` (`type`, `properties`, `required`, `items`, `enum`, `const`, `additionalProperties`, numeric/length/item bounds, `anyOf`/`oneOf`/`allOf`, `nullable`, annotations). `$ref` and `pattern` are rejected with HTTP 400. |
| `tool_choice` | `"none"`, `"auto"` (default with tools), `"required"`, or `{"type": "function", "function": {"name": ...}}`. |
| `parallel_tool_calls` | `false` returns at most one call. |
| History | System/developer, user (text and images), assistant (with `tool_calls`, content may be null) and `tool` messages, in order. Every call must be answered by exactly one result before the conversation continues. |

Generated calls are validated against the offered schema. An invalid call, a
call to an unoffered function or a missing call under `required`/named choice
returns HTTP 502 (`tool_call_validation_failed`); a call cut off by the token
limit returns `finish_reason: "length"` without calls. Streaming publishes each
call in one `delta.tool_calls` chunk only after it is complete and valid; a
failure mid-stream ends with an `error` event and `[DONE]`.

Requests without tools or tool messages use the existing chat path unchanged
(the last user turn is answered).

## Health

`GET /health` keeps its existing fields and adds `hub.text_gen.serving` once the
model is loaded:

```json
{
  "model": "Qwen/Qwen3.6-35B-A3B", "weight_format": "int4", "device": "GPU",
  "tool_calls": true,
  "speculative": {"requested_mode": "auto", "requested_method": "auto",
                  "effective_method": "dflash", "draft": "z-lab/Qwen3.6-35B-A3B-DFlash@0123456789ab",
                  "num_assistant_tokens": 3, "fallback_reason": null},
  "warmup": {"status": "ok", "seconds": 1.8},
  "startup": {"prepare_s": 0.4, "load_s": 61.2, "warmup_s": 1.8},
  "diagnostics": {"openvino_genai": "2026.4.1.0", "draft_revision": "...", "scheduler": {}}
}
```

Local paths are never reported; a local drafter appears as `local IR (<dir name>)`.

## Processing-Time Statistics

`GET /processing-stats` reports workflow-stage and per-model-call timing:
queue wait, latency, TTFT, decode throughput and DFlash acceptance, attributed
to the stage that made each call. Each session's records are also written to
its `logs/` folder, and `Scripts/processing_stats_report.py` turns them into a
Markdown report with a timeline. See
[processing-time-statistics.md](processing-time-statistics.md).
