# Smart Classroom Vision-Language Model (VLM) and Large Language Model (LLM) Serving Design

**Status:** Implementation design. The requirements below are the contract; paragraphs marked **Implemented** describe how the current code meets them, and the table under Section 1 summarizes coverage. Hardware qualification (Section 8) and published performance results remain pending.

## 1. Key Features and Compatibility

This design covers shared model serving, speculative decoding, timing instrumentation, and offline benchmarking while preserving classroom inference interfaces.

| Key Feature | Stakeholder Benefit |
| --- | --- |
| **Qwen3.5, Qwen3.6, or Qwen3.8 model choice** | Serve Qwen3.5-9B INT4 and INT8, Qwen3.6-35B-A3B INT4, and Qwen3.8-27B INT4 and INT8 through the shared OpenVINO service. |
| **Tool calling on port 8000** | OpenAI-compatible function calls and tool-result conversations through `/v1/chat/completions`, enabling agent workflows without a separate endpoint. |
| **Selectable speculative decoding** | Choose DFlash, DFlash2 or supported MTP explicitly, with plain-generation fallback under the `auto` activation policy. |
| **Automatic first-run preparation** | Download the target and required speculative artifacts, convert them when needed, and reuse validated files on later starts. No pre-existing local model files are required. |
| **Backward compatibility** | Retain older models and configuration, the port-8000 API, `/v1/chat/completions`, and the shared classroom generation interface. |
| **Controlled activation** | Complete the warm-up of the selected model pipeline before reporting readiness, show the model's acceleration status, and handle failures safely. |
| **Workflow-stage and model-call timing statistics** | Measure processing time separately for workflow stages, including Automatic Speech Recognition (ASR), video analytics (VA), Optical Character Recognition (OCR), Summary, and Mindmap. Compare individual model calls by model, precision, device, and effective decoding method. |
| **Standalone `context_bench` benchmarking** | Compare model and runtime profiles using repeatable measurements of time to first token (TTFT), time per output token after the first (TPOT), throughput, and memory. Optionally assess retrieval accuracy and generation fidelity against a baseline. See [context-bench-design.md](../context-bench/context-bench-design.md). |

**Preserve existing model support**, including Qwen3-VL-8B-Instruct and Qwen3.5-9B, with unchanged providers, model IDs, precisions, local paths and generation behavior. No configuration migration or default model replacement is required; speculation remains switched off unless enabled. A model without a qualified accelerator continues through plain generation. Qualified serving profiles prepare missing artifacts automatically after software setup; the offline benchmark consumes prepared artifacts.

Keep one target per serving instance. Generating tool calls and consuming tool results are in scope; executing tools remains the client's or controller's responsibility. Multi-model routing, UI redesign, and NPU text-generation support are outside the scope; existing NPU use by other classroom components is unchanged.

**Implemented** (usage: [serving-guide.md](serving-guide.md)):

| Feature | Current implementation |
| --- | --- |
| Model choice | Catalog in [text_gen_profiles.py](../../../components/vlm/text_gen_profiles.py): Qwen3-VL-8B-Instruct (default) and Qwen3.5-9B INT4/INT8, Qwen3.6-35B-A3B INT4, Qwen3.8-27B INT4/INT8, all declared tool-capable. Models outside the catalog keep the existing export path. |
| Speculative decoding | DFlash for Qwen3.6-35B-A3B INT4 only. `dflash2` and `mtp` are accepted settings without a profile: plain generation under `auto`, a startup failure under `"on"`. |
| First-run preparation | [text_gen_prepare.py](../../../components/vlm/text_gen_prepare.py), run by the model owner at load (Section 5). |
| Tool calling | [tool_calls.py](../../../components/vlm/tool_calls.py) and [vlm_chat.py](../../../api/vlm_chat.py) (Section 3). |
| Controlled activation | Warm-up before readiness; `/health` reports `hub.text_gen.serving` (Section 6). |
| Timing statistics | Stage and model-call records, `GET /processing-stats`, per-session logs and a report script: [processing-time-statistics.md](processing-time-statistics.md) (Section 7). |
| `context_bench` | [components/context_bench](../../../components/context_bench/): [context-bench-design.md](../context-bench/context-bench-design.md). |

## 2. Model Profiles

| Model | Target Artifacts | Optional Accelerator |
| --- | --- | --- |
| Previously supported VLM and LLM models | Preserve their supported download and export paths, and precisions | Plain generation; a drafter is not required |
| `Qwen/Qwen3.5-9B` | [INT4 intermediate representation (IR)](https://huggingface.co/OpenVINO/Qwen3.5-9B-int4-ov) or [INT8 IR](https://huggingface.co/OpenVINO/Qwen3.5-9B-int8-ov) | Plain generation; speculative decoding requires a separately qualified profile |
| `Qwen/Qwen3.6-35B-A3B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.6-35B-A3B-int4-ov) | [DFlash](https://huggingface.co/z-lab/Qwen3.6-35B-A3B-DFlash) |
| `Qwen/Qwen3.8-27B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.8-27B-int4-ov) or [INT8 IR](https://huggingface.co/OpenVINO/Qwen3.8-27B-int8-ov) | [DFlash2](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2) (planned: no profile yet, so plain generation) |

A Qwen3.5-9B selection uses `provider: vlm`, `vlm_name: Qwen/Qwen3.5-9B`, and `weight_format: int4` or `int8` under `models.text_gen`. Omit `speculative` for plain generation; listing the target artifacts does not qualify a speculative method or tool-call capability.

A maintained catalog supplies compatible combinations of targets and methods, default drafter sources, immutable revisions, conversion recipes, dependency versions, and tested tuning values. Explicit speculative settings select or override these defaults only within a validated profile. Drafter precision is independent of target precision. Extend the catalog without restricting the existing plain-model loading path.

A source checkpoint is not runtime-ready IR. Each accelerated profile must provide downloadable compatible IR or a tested conversion recipe for downloaded source files, including target hidden-state outputs where needed. Qualify the DFlash2 exporter and runtime independently. Multi-token prediction (MTP) uses the target's bundled prediction head and requires its own artifact and runtime qualification; it does not use either of the two external Dflash and Dflash2 z-lab drafters listed above. Select one mechanism per pipeline, never silently substitute or combine them.

**Implemented:** the Qwen3.6 DFlash profile pins drafter commit `f181eece646affea2c38b2765f1aaa01a9734ccd`, downloads only its configuration and weight files, and exports it to INT4 IR with the DFlash classes built into optimum-intel 2.2.0 (no repository code). The tested defaults are `num_assistant_tokens: 3` (range 1–15), OpenVINO GenAI 2026.3 or later, an f16 KV cache, and a scheduler with `max_num_seqs: 1`, `num_linear_attention_blocks: 17` and prefix caching off; the cache size is left to the runtime. When the stock target export lacks the hidden-state metadata the drafter needs, a derived target directory carries it (Section 5).

## 3. Architecture

In the design requirements, serving has two phases: startup preparation and request handling.

![Startup and request flow for existing and new models](assets/vlm-llm-serving-overview.svg)

Startup:
- A shared helper prepares model files once. The model owner, which can be the application, a supervised worker, or an independently operated server, loads and warms the model before serving classroom requests.
- Workers reuse prepared artifacts after restart.

Request Handling:
- Classroom workflows send requests to the ready model. The service limits how many requests it admits, can stream responses as they are generated, and supports cancellation.
- If a request is cancelled while native inference is still running, the service must keep that model capacity reserved until inference finishes.

Model upgrades do not require a new deployment topology. External clients do not download or manage the server’s model files. The server reports its actual model and acceleration state.

**Implemented:** the owner is the backend process itself. `ModelManager` warms `text_gen` at startup through `TextGenHandler`, which wraps one `VLMTextGen` pipeline in a `CapabilityRunner` (`concurrency` and `queue_max` from `models.text_gen`; a full queue returns HTTP 503). A streamed request holds its slot until native generation has stopped, including after a client disconnect, which cancels generation at the next token. A consumer that abandons a stream without closing it still releases the slot when the stream is garbage-collected.

### Tool Calls on Port 8000

**`POST /v1/chat/completions` on port 8000 must support OpenAI-compatible function (tool) calling**, in streaming and non-streaming requests. Qwen3.6 and Qwen3.8 serving profiles must pass the tool-call qualification; older tool-capable models use the same contract, while ordinary chat remains available for models without tool support. All serving ownership modes expose this contract through the same application endpoint.

| Contract | Required Behavior |
| --- | --- |
| Conversation | Preserve the full ordered `messages` history: system or developer, user, assistant, and tool turns, including supported image content. Do not reduce it to the last user prompt. Assistant messages may have null content when they contain tool calls. |
| Tool definitions | Accept request-level `tools` entries with `type: "function"`, function name, optional description, and a JSON Schema `parameters` object. Render definitions and history through the selected model's tool-aware chat template. |
| Tool selection | Support `tool_choice: "none"`, `"auto"`, `"required"`, or a named function object. Default to `auto` when tools are supplied, otherwise `none`. Reject choices referring to absent tools. Honor `parallel_tool_calls: false` by returning at most one call; multiple calls, when allowed, each require a distinct ID. |
| Tool response | Return `choices[].message.tool_calls` with stable `id`, `type: "function"`, `function.name`, and JSON-encoded `function.arguments`. Normalize model-specific tool syntax into this structure. Finish a valid tool-call turn with `finish_reason: "tool_calls"`; an ordinary completed text turn uses `"stop"`. |
| Tool results | The client appends the assistant tool-call message and a `role: "tool"` message with matching `tool_call_id` and result `content`, then submits the conversation again. Validate call-to-result associations and duplicate or missing results in the submitted history; server-side conversation storage is not required. |
| Streaming | Emit OpenAI-compatible Server-Sent Events (SSE) `delta.tool_calls` with stable call indexes and IDs. Buffer each generated call until its name and arguments are complete and validated, then publish it; finish with `finish_reason: "tool_calls"` and `[DONE]`. Do not expose partially generated arguments as a completed call. |

Tool-call sequence from the design requirements:

1. Request with tools: The client sends a request that includes tool definitions.
2. Assistant tool call: The assistant returns a tool call: a request to use one of those tools, with its name and arguments.
3. Client-authorized execution: Execution is client-authorized. The controller independently validates the arguments, authorizes execution, and bounds tool-loop iterations. The serving process does not execute a function, open a shell, or performs an action merely because the model requested it.
4. Tool result message: The client appends the assistant's tool-call message and a `role: "tool"` message containing the result and matching `tool_call_id`, then resubmits the conversation.
5. Assistant answer or next tool call: The assistant uses the result to answer, or returns another tool call and the sequence continues.

Tool-call validation and failure handling from the design requirements:

- Before invoking generation, the serving endpoint validates request schemas, tool names, selection options, and model capabilities.
- The serving endpoint returns a clear 4xx error for malformed requests or unsupported tool or schema features; it must not ignore them.
- The service endpoint validates each generated call against the offered function’s supported JSON Schema, not only its required keys.
- The service endpoint does not report an invalid, truncated, or missing required call as a successful tool invocation. It preserves failure and truncation semantics.
- If a stream has already started, the serving endpoint terminates it with an error rather than signaling a successful tool-call completion.
- The controller independently validates arguments, authorizes execution, and limits tool-loop iterations.
- The controller treats tool results as untrusted conversation data; it does not authorize further actions.

**Implemented** ([tool_calls.py](../../../components/vlm/tool_calls.py), [vlm_chat.py](../../../api/vlm_chat.py)):

- A request uses the tool path when it has `tools` or `tool_choice`, or its history contains tool calls or results; any other request keeps the existing chat path (last user turn).
- The supported JSON Schema subset covers `type`, `properties`, `required`, `items`, `enum`, `const`, `additionalProperties`, numeric, length and item bounds, `anyOf`/`oneOf`/`allOf`, `nullable` and annotations. Other keywords, such as `$ref` and `pattern`, are rejected with HTTP 400, as are malformed definitions, history or choices.
- Tool capability comes from the catalog and from the chat template rendering tools. A model without it rejects tool requests with HTTP 400; `tool_choice: "none"` still works.
- Qwen3 JSON calls and Qwen3.5+ `<function=...>` XML calls are both normalized. Calls inside reasoning are ignored, and reasoning is returned as `reasoning_content`, never in `content`.
- `"required"` and named choices are enforced: the assistant turn starts with the opening of a call in the model's syntax (reasoning closed first).
- An invalid call, or a call to a function not offered, returns HTTP 502 (`tool_call_validation_failed`). A token-limited turn returns `finish_reason: "length"` without calls, even when calls before the cut were complete.
- Streaming holds calls until the turn is complete. A rejected call or a generation failure after the stream starts ends it with an `error` event and `[DONE]`; generation failures report a generic message, with details only in the server log.
- Images must be inline `data:image/` URLs on both paths; the server never fetches a URL or reads a local file named by a request. `max_tokens` is accepted as an alias of `max_completion_tokens`, and both must be positive.

## 4. Configuration

- **Reuse the current configuration structure and add an optional `models.text_gen.speculative` block.**
- Keep the activation policy (`mode`) separate from the decoding mechanism (`method`) and from the draft model’s identity and source.
- Continue to select the target with `vlm_name` and `weight_format`.
- Do not rename existing keys or add top-level blocks.

The following example uses the structure of [config.yaml](../../../config.yaml), selects Qwen3.6 INT4 and enables DFlash, the implemented accelerated profile. It is an illustrative profile, not a snapshot of every installation's values. Preserve existing generation, admission, chunking and segmentation settings when merging it. Omitting `speculative` preserves plain generation. The shipped `config.yaml` keeps Qwen3-VL-8B-Instruct with `mode: "off"`. A DFlash2 selection (Qwen3.8 with `method: dflash2`, `draft_model: z-lab/Qwen3.8-27B-DFlash2`) is validated the same way, but runs plain under `auto` until its profile exists.

```yaml
models:
  text_gen:
    provider: vlm
    vlm_name: Qwen/Qwen3.6-35B-A3B
    device: GPU
    weight_format: int4
    max_new_tokens: 5120
    concurrency: 1
    queue_max: 8

    speculative:
      mode: auto
      method: dflash
      draft_source: huggingface
      draft_model: z-lab/Qwen3.6-35B-A3B-DFlash
      draft_revision: null
      num_assistant_tokens: null

    chunking:
      enabled: true
      max_prompt_tokens: auto
      max_content_tokens: 24000
      gpu_memory_safety_margin: 0.6
      map_max_new_tokens: 1536

    segmentation:
      window_max_new_tokens: 1024
      topics_target: 20
      topics_min: 15
      topics_max: 25
```

| Configuration Item | Required Behavior |
| --- | --- |
| Existing `provider`, `vlm_name`, `device`, `weight_format` | Keep names and meanings. For the new models use `provider: vlm`; select a listed model and precision combination. Keep an older installation's selection unless the operator changes it. |
| Existing `max_new_tokens`, `concurrency`, `queue_max` | Retain the installation's generation and admission limits; 5120, 1, and 8 are example values. A larger model does not automatically increase these limits. |
| Existing `chunking` and `segmentation` | Preserve the nested structure and configured values. Validate context and memory budgets for the selected model; change tuning only when measurements justify it. |
| New optional `speculative` block | Select activation policy, method, and draft artifacts without changing target or workflow settings. Defaults and validation are defined below. |

### Speculative Settings

| Field under `speculative` | Values and Default | Purpose |
| --- | --- | --- |
| `mode` | `"off"` (default), `auto`, `"on"` | Disable acceleration, allow plain fallback, or require acceleration. This is not the algorithm name. |
| `method` | `auto` (default), `dflash`, `dflash2`, `mtp` | Select the decoding mechanism. `auto` selects the catalog's declared method, not trial-and-error loading. Future methods require an explicit supported profile. |
| `draft_source` | `null` (profile default), `huggingface`, `local`, `target` | Distinguish a Hub repository, an explicit local IR directory, and target-bundled MTP artifacts. Other sources require a supported adapter and profile. |
| `draft_model` | Repository ID or local directory; `null` selects the profile default | Identify the external drafter for DFlash or DFlash2. For MTP, set to null: use the target's prediction head, not a second model. |
| `draft_revision` | Immutable repository commit (a full 40-character hash); `null` selects the profile's pinned revision | Reproduce a Hub download. Reject non-null values for `local` or `target`; bundled MTP inherits the target revision. |
| `num_assistant_tokens` | Positive integer; `null` selects the tested default for the selected method and profile (DFlash: 3, range 1–15, and at most the drafter's block size minus one) | Control the draft block size within the selected runtime's supported range. Do not reuse DFlash tuning with either DFlash2 or MTP without validation. |

| Selected Target and Method | Draft Settings |
| --- | --- |
| Qwen3.6 INT4 with `dflash` (implemented) | `draft_source: huggingface`, `draft_model: z-lab/Qwen3.6-35B-A3B-DFlash` |
| Qwen3.8 INT4 or INT8 with `dflash2` (planned) | `draft_source: huggingface`, `draft_model: z-lab/Qwen3.8-27B-DFlash2` |
| Target with a qualified bundled `mtp` head (planned) | `draft_source: target`, `draft_model: null`; download required MTP files with the target |

For example, replace only the speculative block with the following when the selected target has a qualified MTP profile:

```yaml
speculative:
  mode: auto
  method: mtp
  draft_source: target
  draft_model: null
  draft_revision: null
  num_assistant_tokens: null
```

Resolve and Validate:
- The helper resolves defaults before downloading, then validates the complete combination of target, method, source, and revision against artifact metadata and the supported profile.
- The model-serving software never changes an explicitly selected method if it fails; in `mode: auto`, the software falls back to the plain generation method.
- Unknown methods, contradictory sources, mismatched drafters, and out-of-range tuning fail the validation rather than triggering fallback. 
- In `"off"` mode, the helper ignores dormant speculative settings and prepares only the target.
- **Implemented:** `resolve_plan()` in [text_gen_profiles.py](../../../components/vlm/text_gen_profiles.py) applies these rules before any model work, so invalid settings under `auto` or `"on"` fail at startup. Bare YAML `off`/`on` booleans are accepted for `mode`.

Prepare Artifacts:
- The helper uses the catalog’s pinned Hub sources for first-run downloads. `draft_source: local` requires a non-empty `draft_model` directory and a null `draft_revision`; the helper validates the existing IR and does not download a replacement if it is missing. 
- The helper resolves relative directory paths from the Smart Classroom application root (`smart-classroom/Windows/`).
- `draft_source: target` is valid only with MTP, and requires `draft_model` and `draft_revision` to be set to null.
- The startup preparation flow ensures that a source override or revision cannot bypass compatibility checks, enable arbitrary URLs or execute repository code.
- The manifest records resolved settings and actual artifact versions, including defaults.

Tool Calls:
Tool definitions and selection are per-request API fields (`tools`, `tool_choice`, and `parallel_tool_calls`), not new YAML settings or a separate service. Record tool and template capability in the model profile so unsupported requests fail before streaming; no `enable_tool_call` configuration flag is needed.


## 5. Model Preparation

The model owner prepares its artifacts when it loads the warm model, before it reports ready (`components/vlm/text_gen_prepare.py`, called from the VLM load). Every startup path therefore prepares the same way and needs no launcher step or switch: [start-smart-classroom.ps1](../../../start-smart-classroom.ps1), the desktop app ([start-desktop-app.ps1](../../../start-desktop-app.ps1)) and `python main.py`. The first start downloads or converts what is missing; later starts only validate. Dependent services already wait for the owner's `/health` before using the model. Request handlers never download or convert files.

1. **Select:** Resolve the target and speculative policy, method and source. Validate explicit settings, then select the compatible catalog profile. A recognized method without runtime/profile support means plain generation in `auto` or an actionable failure in `"on"`.
2. **Prepare:** Download the target's catalog IR and, for Hub drafters, the pinned drafter files over HTTPS. For `local`, validate the specified IR directory without downloading a replacement drafter. For MTP, acquire the target's bundled head and metadata without downloading an unrelated external model. Use runtime-ready IR directly; convert downloaded sources only through the profile's qualified recipe. Network failures do not trigger unrelated export attempts.
3. **Validate:** Check required files, integrity, tokenizer/processor compatibility, runtime versions and target/drafter graph interfaces. Preserve the ordinary target if accelerated export needs separate IR. Record a manifest without overwriting active files or changing legacy model paths.
4. **Activate:** Load the resolved artifacts and run warm-up. Report readiness only after success; a completed download alone is not a ready model.

Create storage on demand, use resumable staging and per-artifact locks, and publish only complete validated artifacts. Bound retries and check disk space for weights and conversion intermediates. Keep prior valid artifacts for rollback. Legacy files can be validated and reused without claiming provenance that is not known.

**Implemented:**

| Artifact | How it is prepared and reused |
| --- | --- |
| Target IR, `models/openvino/<model>/<weight_format>` | Catalog models download the pre-converted `OpenVINO/<model>-<weight_format>-ov` IR (resumable, 3 attempts); other models use the existing local export. Reused when the IR, tokenizer and detokenizer are present. The manifest records no revision for it, since the download is not pinned. The tokenizer IR is refused if a newer openvino-tokenizers release exported it. |
| DFlash drafter source, `models/hf/<org>__<repo>/<commit>` | Configuration and weight files only, at the pinned commit, after a free-space check (2.2x the checkpoint). |
| DFlash drafter IR, `models/openvino/<drafter>/int4` | Exported offline in a separate process; `.prepared.json` records the commit, and the IR is reused while it matches the pin. |
| Drafter with its own INT4 lm_head, `<drafter>/int4-lmhead` (the one loaded) | The target's INT8 head requantized to INT4 and attached to the drafter, so the runtime no longer reads the full INT8 head on every draft pass. Rebuilt when the SHA-256 of the target or drafter XML changes; if it cannot be built, the stock drafter is used. Not applied to `draft_source: local`. |
| Derived target, `<model>/<weight_format>-dflash` | Only when the stock target lacks `hidden_states_decoder_layers`: weights hard-linked, XML annotated, the ordinary target untouched; rebuilt when the target XML hash changes. |
| Manifest, `models/openvino/.manifests/<model>-<weight_format>.json` | Resolved settings, drafter commit, decision, reason and timings. |

Drafter and derived artifacts are staged in `.partial` directories and published whole. Each artifact has a `.lock` file that records its owner's process ID and start time, so a lock left by a dead process is recovered even when Windows reuses the ID. A superseded or stale artifact is moved aside with a timestamp suffix, never deleted. Under `auto`, a drafter download, export or file-system failure falls back to plain generation; a drafter incompatible with the target always fails.

To run offline, start once with network access (or copy prepared `models/` directories): validated artifacts are reused without network access. Install trusted exporter dependencies during software setup. Validate paths and downloaded metadata, never execute repository code, and preserve TLS verification. Pass arguments as data and credentials/proxy settings through the environment without logging secrets.

## 6. Generation and Failure Policy

DFlash/DFlash2 uses an external drafter; MTP uses the target's bundled prediction head. The target verifies proposed tokens. The qualified OpenVINO runtime owns drafting and acceptance; the application selects one method and enforces readiness and request policy.

Validate DFlash/DFlash2 hidden-state outputs and vocabulary alignment; for MTP, validate the bundled head and its target/runtime contract instead. Check the complete runtime/exporter dependency set for each method. Keep method-specific scheduler and draft-block memory settings isolated from plain generation. Budget target, speculative artifacts, image processing and other classroom memory together.

Initially accelerate text-only greedy generation. Preserve image support through tested plain VLM decoding; do not claim image-encoding speedups. Reject unsupported sampling on an active speculative pipeline before streaming rather than silently changing the request. Plain generation retains each model's supported behavior. `"on"` requires speculative readiness at startup, not acceleration of every request.

Tool calling is independent of speculative decoding: it must work with speculation off, and every advertised tool-capable DFlash/DFlash2/MTP profile must pass the same call/result and streaming tests. Speculation must not drop tool definitions, change call IDs, expose unverified draft tokens or bypass argument validation. Reject an unsupported model/method/tool combination before generation; do not silently remove tools or switch speculative methods.

| Condition | `"off"` | `auto` | `"on"` |
| --- | --- | --- | --- |
| No qualified profile for the selected method, including an older model | Use plain model | Use plain model; report reason | Fail with guidance to use plain mode |
| Missing selected files, with a qualified profile available | Acquire target only | Prepare target and method-specific artifacts | Prepare target and method-specific artifacts |
| Target unavailable after permitted preparation | Fail | Fail | Fail |
| Speculative artifact acquisition, conversion or activation fails | Not applicable | Warm a plain pipeline once, after safe cleanup | Fail |
| Invalid active method/source/tuning, mismatched target/drafter or integrity failure | Fail for active target | Fail | Fail |

`local` draft sources prohibit replacement downloads. A normal `auto` fallback is not successful accelerator qualification; qualify with `"on"`.

If native cleanup cannot be confirmed, stop the model process before recovery. Retain the plain-mode decision for that launch so recovery does not repeatedly activate a failing drafter. Never replay a partially streamed request. Roll back by restoring the previous model/artifacts or disabling speculation and restarting, not by deleting caches.

Health reports the target, tool-call capability, requested/effective method, drafter identity or target-bundled head, warm-up result and sanitized fallback reason. Detailed revisions, tuning and runtime versions remain available for diagnostics without exposing private local paths. Do not log sensitive tool arguments or results by default.

**Implemented** ([text_gen_vlm.py](../../../components/vlm/text_gen_vlm.py)):

- **Warm-up and fallback.** Readiness follows one 2-token greedy generation. Under `auto`, a failed load or warm-up with the drafter discards that in-process pipeline (released and garbage-collected) before the plain pipeline is warmed. The plain decision is kept for the process lifetime.
- **Request policy.** While DFlash is active, requests are greedy with the profile's fixed draft window. A request with `temperature > 0` is rejected with HTTP 400 before generation, and image requests run on the same pipeline.
- **Health.** `GET /health` adds `hub.text_gen.serving` with these fields:
  - `model`, `weight_format`, `device`, `tool_calls`;
  - `speculative` (`requested_mode`, `requested_method`, `effective_method`, `draft`, `num_assistant_tokens`, `fallback_reason`);
  - `warmup`;
  - `startup` (`prepare_s`, `load_s`, `warmup_s`);
  - `diagnostics` (GenAI version, drafter revision, scheduler).

  Local paths are stripped from reasons, and a local drafter is shown only by its directory name.

## 7. Processing-Time Statistics

Collect statistics at two levels: **workflow-stage elapsed time** for the classroom experience and **individual model-call time** for inference cost. These are nested measurements, not interchangeable values. Existing timing sources are identified under Collection and Reporting; the remaining coverage requires implementation.

### Workflow Stages

Measure each enabled stage from execution start through completion of its output, including preprocessing, model calls and postprocessing. Record admission/queue wait separately and include it in request end-to-end latency. Use seconds for stage durations and milliseconds for per-frame or per-call latency.

| Stage | Processing-time boundary and breakdown | Workload and additional statistics |
| --- | --- | --- |
| Media preparation | Input decoding, audio extraction and chunk preparation | Media duration, chunk count and preparation seconds; identify work already included in ASR |
| ASR | Consume audio chunks through final transcript persistence; separate input wait, transcription and optional diarization | Audio seconds, chunk count, ASR and diarization model-call times; real-time factor = processing seconds / audio seconds for a fixed recorded input |
| VA (video analytics) | First accepted frame through final analytics output for a fixed clip; separate decode, model inference, tracking and aggregation | Per-stream processed/dropped frames, achieved FPS, frame-latency p50/p95 and each detector, pose, classifier or re-identification model's time; report live observation duration separately |
| OCR | Frame/page selection through persisted recognized text; separate extraction, detection, recognition and merge | Frames/pages processed and per-image latency; report board OCR and document OCR separately |
| Summary | Summary execution through final saved summary, including map/fold/reduce calls when chunking is active | Strategy, chunk count, map/fold and reduce times, total seconds, time to first token (TTFT), input/output tokens and decode tokens/s |
| Mindmap | Summary input preparation through generated, validated and saved mindmap | Model-call time, validation/persistence time and any repair attempts; distinguish insufficient-input fallback from model generation |
| Topic segmentation | Transcript preparation through validated and saved topics | Window count, per-window model times and topic count; measure subsequent embedding/indexing separately |
| Report | Session-data collection through completed report generation and persistence | Collection, model generation and rendering/export times; identify cached re-selection or reports requiring no model call |
| Content search ingestion | Accepted ingestion task through searchable content | Queue wait, extraction/video captioning, embedding and indexing times; document/page/frame/chunk counts |
| RAG Q&A | Accepted question through final answer | Retrieval, reranking, prompt preparation and generation times; TTFT and input/output tokens |
| Grading | Accepted grading task through completed result | Layout/detection, OCR/VLM calls and result assembly; page/question counts and retry times |

ASR, VA and board OCR can overlap, and several stages may share the text-generation queue. Measure workflow wall time directly from workflow start to completion of all requested outputs; **do not sum stage durations to infer end-to-end latency**. Record the enabled stages and whether the run is live, recorded-media replay or an isolated stage benchmark. For live workflows, also report time from input completion to final output so recording duration is not mistaken for inference cost.

### Individual Models

Time each invocation at the model owner, retaining its parent stage and an opaque run/request identifier. Group by actual model/artifact revision, precision, device, hardware platform, runtime version and effective decoding method. A shared Qwen model must remain attributable to Summary, Mindmap, segmentation, reports, captioning, Q&A or grading rather than becoming one unattributed total.

| Model-call statistic | Definition |
| --- | --- |
| Call latency | Monotonic elapsed time from model invocation to final output, excluding admission wait; include preprocessing/postprocessing performed inside that boundary and label it accordingly. Report runtime inference-only time separately when available. |
| Generative breakdown | Input/image preparation, prefill and decode time when exposed by the runtime; model TTFT, prompt/output token counts and decode tokens/s. Do not estimate unavailable subphase timings by subtraction. |
| Non-generative breakdown | Inference time per audio chunk, image, frame or batch, with input dimensions/duration and batch size; keep detection, recognition, embedding and reranker models separate. |
| Speculative decoding | Requested/effective method and fallback status; target verification time, drafter or bundled-head time and accepted/proposed tokens when exposed by the runtime. These are subphases of the call, not extra workflow stages. |
| Startup | Download, conversion, model load/compile and warm-up times recorded separately from warm-request latency. |

Use the generation metric definitions and source/boundary rules in the [benchmark metrics section](../context-bench/context-bench-design.md#7-iteration-metrics-and-comparison-rules). Keep model TTFT distinct from client-visible TTFT, which also includes request preparation, queueing, transport and earlier map calls. Record durations locally within each process; do not subtract monotonic timestamps from different processes or hosts.

For every model/precision in Section 2, report call-latency mean/p50/p95, TTFT and decode throughput across the platform/method matrix in Section 8. Include the installed model as the compatibility baseline. ASR, VA, OCR, embedding and reranker models use the applicable per-call statistics with their actual configured identities.

### Collection and Reporting

Reuse existing timing sources while preserving their meanings: [ASR](../../../components/asr_component.py) writes `performance.transcription_time`; [Summary](../../../components/summarizer_component.py) writes `performance.summarizer_time`, `performance.summary_map_time`, `performance.ttft`, `performance.reduce_ttft` and `performance.tps`; [Report](../../../components/report_generator/report_generator.py) writes collection, generation and total times. These are component timers, not isolated model benchmarks. ASR includes upstream input waiting and optional diarization; the report generation timer also includes rendering/persistence. [Hardware monitoring](../../../monitoring/monitor.py) provides utilization, memory and power samples, not model-call latency. Keep these existing fields compatible and add the missing stage/call measurements at their owning boundaries.

Retain one record per stage attempt and model invocation so repeated calls, retries and failures are not overwritten by a last-value metric. Use monotonic clocks and finalize timers on success, failure or cancellation; for streaming, measure through generator completion, not generator creation. Separate client cancellation time from the end of any continuing native inference. Record status, counts and timing metadata only, with bounded retention; exclude prompts, transcripts, images, tool arguments/results, student identifiers, credentials and private paths.

For each stage and model group, publish successful sample count, total processing time, mean, min/max, p50 and p95, plus failed/cancelled attempt counts and their elapsed time separately. Mark skipped stages as not applicable and missing or unsupported measurements as unavailable, never zero. Treat existing negative sentinel values as unavailable. Preserve raw samples, units, measurement boundaries and the percentile calculation method; a single run is an observation, not a latency distribution.

Compare repeated warm runs using the same fixed inputs, prompt templates, token limits, chunking, concurrency, media settings and enabled stages. Publish hardware/driver/runtime/artifact versions, input durations or dimensions, token counts, warm-up/repetition counts, quality outcomes and an evidence link with every result. Separate isolated model benchmarks from concurrent classroom runs and cold-start measurements. Compute speedup only between matched plain/accelerated cases using the same latency statistic; report actual fallback as plain generation, not accelerated success.

### Implemented Coverage

See [processing-time-statistics.md](processing-time-statistics.md) for fields and usage.

| Level | Recorded now | Not yet recorded |
| --- | --- | --- |
| Workflow stages ([stage_tracker.py](../../../utils/stage_tracker.py)) | `transcribe`, `va`, `summarize`, `mindmap`, `segmentation` and `report`: one record per attempt with status, UTC start/end and duration | Media preparation, content-search ingestion, and the retrieval/reranking breakdown of RAG Q&A |
| Stages seen through model calls | `board_ocr`, `document_ocr`, and `/v1/chat/completions` callers named by the `X-SC-Stage` header (`qa`, `video_captioning`, `grading`, otherwise `chat_api`) | — |
| Model calls ([processing_stats.py](../../../utils/processing_stats.py)) | `text_gen`, `asr` and `ocr`: queue wait, latency, status, client cancellation, and for text generation TTFT, TPOT, token counts and DFlash accepted/drafted tokens | VA, embedding, reranking and grading layout/detection models; target-versus-drafter time inside a DFlash call |
| Startup | Preparation, load and warm-up seconds in `/health` | A per-run history |

Records are held in memory (the latest 4,000 of each kind) for `GET /processing-stats` and appended to `<session>/logs/stage_events.jsonl` and `model_calls.jsonl`. They contain timing metadata only. [processing_stats_report.py](../../../Scripts/processing_stats_report.py) turns either source into a Markdown report with a per-session timeline. That report:
- counts each stage attempt's own model calls, failed and cancelled included;
- computes DFlash acceptance only from calls that report both counters.

## 8. Release Decisions

| Area | Required checks |
| --- | --- |
| Backward compatibility | Load unchanged older configurations; retain existing key names, token/queue limits, chunking, segmentation and service endpoints. Test supported providers/model IDs, precisions and local paths; no drafter download when off; plain fallback in `auto`; no regressions from runtime dependency upgrades. |
| Model/precision support | For every Section 2 profile, test empty-cache preparation, warm-up and later reuse of the validated artifacts. Plain mode downloads only the target; an accelerated case requires all artifacts for its selected method. |
| Port-8000 tool calling | End-to-end function definition -> tool call -> tool result -> answer through `/v1/chat/completions`, with streaming and non-streaming clients. Test `none`/`auto`/`required`/named choices, multiple-call IDs, `parallel_tool_calls: false`, full history, malformed arguments, missing results, truncation, unsupported models and no server-side tool execution. |
| Speculative configuration | Missing/mode-only blocks, all supported methods, explicit/default Hub revisions, local path handling and tuning bounds. Reject cross-model drafters and MTP with an external draft source/model; bundled MTP must never trigger a z-lab download. |
| Classroom quality | Streaming/non-streaming text, images, supported thinking/structured output, cancellation and queue limits; summaries, mind maps, segmentation, reports, RAG Q&A, video summaries and grading. |
| Reliability | Invalid pairs and corrupt artifacts, network/disk failures, interrupted/concurrent downloads, safe startup fallback, and identical preparation from both launchers on Windows PowerShell 5.1/7. |
| Performance | Repeated plain/accelerated comparisons: answer quality, time to first token, tokens/s, end-to-end p50/p95 latency and peak memory. Separate download/conversion/compile time from inference. |
| Timing statistics | Publish stage and individual-model results defined in Section 7 for each qualification case. Verify attribution for shared models, overlapping stages, streaming completion, retries, failures, cancellation and skipped stages; retain raw samples and do not present unavailable timings as zero or pending cases as measured. |
| Context bench | Complete the [benchmark implementation and tests](../context-bench/context-bench-design.md#10-implementation-sequence-and-verification); verify exact-context and matched-profile measurements, separate accuracy verdicts, interruption-safe evidence, nonzero failure exits and unchanged source/serving artifacts. Publish model-call evidence without presenting it as full classroom-workflow timing. |

The required GPU matrix covers Arrow Lake (ARL) and Panther Lake (PTL): Qwen3.5-9B INT4/INT8 plain on both platforms (four cases), plus Qwen3.6 INT4 and Qwen3.8 INT4/INT8 with plain and their respective DFlash/DFlash2 methods on both platforms (twelve cases). These sixteen cases are planned qualification, not reported passes; DFlash2 remains blocked until its adapter/runtime is qualified. Add older-model regressions and separate MTP cases for each advertised target/precision/platform; do not infer support across methods. Include tool-call round trips for tool-capable profiles. CPU qualification is separate; identify exact hardware, artifacts, runtime/driver versions and workload settings in every result.

**Verified so far (not qualification):**
- **Unit tests** (`components/tests`, `tests/unit`, `model_manager/test`) cover:
  - configuration resolution, preparation and locking;
  - the tool-call contract, including truncation, forced choices, malformed history and stream failures;
  - stream slot release and the timing records.
- **Tool calls, end to end:** one Arc 140T (Arrow Lake) passed 10 tool-call scenarios through the `openai` client on four profiles:
  - Qwen3-VL-8B, Qwen3.5-9B and Qwen3.8-27B INT4, plain;
  - Qwen3.6-35B-A3B INT4 with DFlash.
- **DFlash performance:** `context_bench` measured DFlash for Qwen3.6 INT4 on the same machine.

The ARL/PTL matrix above remains planned.
