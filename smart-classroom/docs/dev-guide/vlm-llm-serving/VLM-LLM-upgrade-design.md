# Smart Classroom VLM/LLM Serving Design

**Status:** Proposed design for stakeholder review. New model/accelerator combinations require qualification before release.

## 1. Key Features and Compatibility

The upgrade expands model choice without changing how classroom applications access inference.

| Key feature | Stakeholder benefit |
| --- | --- |
| **Qwen3.6 / Qwen3.8 model choice** | Qwen3.6-35B-A3B INT4 and Qwen3.8-27B INT4/INT8 through the shared OpenVINO service. |
| **Tool calling on port 8000** | OpenAI-compatible function calls and tool-result conversations through `/v1/chat/completions`, enabling agent workflows without a separate endpoint. |
| **Selectable speculative decoding** | Choose DFlash, DFlash2 or supported MTP explicitly, with plain-generation fallback under the `auto` activation policy. |
| **Automatic first-run preparation** | Download the target and required speculative artifacts, convert when needed, and reuse validated files on later starts. No pre-existing local model files are required. |
| **Backward compatibility** | Retain older models and configuration, the port-8000 API, `/v1/chat/completions`, and the shared classroom generation interface. |
| **Controlled activation** | Warm-up before readiness, visible acceleration status and safe failure handling before release. |

**Older models remain supported**, including Qwen3-VL-8B-Instruct and Qwen3.5-9B. Preserve supported providers, model IDs, precisions, local paths and generation behavior. No configuration migration or default model replacement is required; speculation remains off unless enabled. A model without a qualified drafter can continue through plain generation. Software setup is a prerequisite, but manual model downloads or exports are not.

Keep one target per serving instance. Generating tool calls and consuming tool results are in scope; executing tools remains the client/controller's responsibility. Multi-model routing, UI redesign and NPU support are outside scope. Compatibility is a release requirement, not a claim that untested model/runtime combinations already work.

## 2. Model Profiles

| Model | Target artifacts | Optional accelerator |
| --- | --- | --- |
| Previously supported VLM/LLM models | Preserve their supported download/export paths and precisions | Plain generation; a drafter is not required |
| `Qwen/Qwen3.6-35B-A3B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.6-35B-A3B-int4-ov) | [DFlash](https://huggingface.co/z-lab/Qwen3.6-35B-A3B-DFlash) |
| `Qwen/Qwen3.8-27B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.8-27B-int4-ov) or [INT8 IR](https://huggingface.co/OpenVINO/Qwen3.8-27B-int8-ov) | [DFlash2](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2) |

A maintained catalog supplies compatible target/method combinations, default drafter sources, immutable revisions, conversion recipes, dependency versions and tested tuning values. Explicit speculative settings select or override these defaults only within a validated profile. Drafter precision is independent of target precision. Extend the catalog without restricting the existing plain-model loading path.

A source checkpoint is not runtime-ready IR. Each accelerated profile must provide downloadable compatible IR or a tested conversion recipe for downloaded source files, including target hidden-state outputs where needed. DFlash2 requires independent exporter/runtime qualification. MTP (multi-token prediction) uses the target's bundled prediction head and requires its own artifact/runtime qualification; it does not use either z-lab drafter above. Select one mechanism per pipeline, never silently substitute or combine them.

## 3. Architecture

Separate startup preparation from request handling. A shared helper prepares files once; the model owner loads and warms them before serving classroom requests.

![Startup and request flow for existing and new models](assets/vlm-llm-serving-overview.svg)

The diagram uses a fixed **16:9 canvas, 1600 x 900**, matching a widescreen PowerPoint slide (13.333 x 7.5 inches). Its SVG format scales without losing clarity; preserve the aspect ratio when inserting it into a slide.

Model upgrades do not require a new deployment topology. The owner may be the application, a supervised worker or an independently operated server. Workers reuse prepared artifacts on restart. External clients do not download or manage the server's model files; the server reports its actual model and acceleration state.

Keep bounded request admission, streaming and cancellation. A cancelled request must not release model capacity while native inference is still active.

### Tool Calling on Port 8000

**`POST /v1/chat/completions` on port 8000 must support OpenAI-compatible function/tool calling**, in streaming and non-streaming requests. Qwen3.6/Qwen3.8 serving profiles must pass tool-call qualification; older tool-capable models use the same contract, while ordinary chat remains available for models without tool support. All serving ownership modes expose this contract through the same application endpoint.

| Contract | Required behavior |
| --- | --- |
| Conversation | Preserve the full ordered `messages` history: system/developer, user, assistant and tool turns, including supported image content. Do not reduce it to the last user prompt. Assistant messages may have null content when they contain tool calls. |
| Tool definitions | Accept request-level `tools` entries with `type: "function"`, function name, optional description and a JSON Schema `parameters` object. Render definitions and history through the selected model's tool-aware chat template. |
| Tool selection | Support `tool_choice: "none"`, `"auto"`, `"required"`, or a named function object. Default to `auto` when tools are supplied, otherwise `none`. Reject choices referring to absent tools. Honor `parallel_tool_calls: false` by returning at most one call; multiple calls, when allowed, each require a distinct ID. |
| Tool response | Return `choices[].message.tool_calls` with stable `id`, `type: "function"`, `function.name` and JSON-encoded `function.arguments`. Normalize model-specific tool syntax into this structure. Finish a valid tool-call turn with `finish_reason: "tool_calls"`; an ordinary completed text turn uses `"stop"`. |
| Tool results | The client appends the assistant tool-call message and a `role: "tool"` message with matching `tool_call_id` and result `content`, then submits the conversation again. Validate call/result associations and duplicate or missing results in the submitted history; server-side conversation storage is not required. |
| Streaming | Emit OpenAI-compatible SSE `delta.tool_calls` with stable call indexes and IDs. Buffer each generated call until its name and arguments are complete and validated, then publish it; finish with `finish_reason: "tool_calls"` and `[DONE]`. Do not expose partial generated arguments as a completed call. |

The interaction is **request with tools -> assistant tool call -> client-authorized execution -> tool-result message -> assistant answer or next tool call**. The serving process never executes a function, opens a shell or performs an action merely because the model requested it.

Validate request schemas, names, selection options and model capabilities before generation; reject malformed requests or unsupported tool/schema features with a clear 4xx error instead of ignoring them. Validate generated calls against the offered function's supported JSON Schema, not just required keys. An invalid, truncated or missing required call must not be returned as a successful tool invocation; preserve failure/truncation semantics, and terminate an already-started stream with an error rather than claiming a successful tool-call finish. The controller independently validates arguments, authorizes execution and bounds tool-loop iterations. Treat tool results as untrusted conversation data, not authorization to execute further actions.

## 4. Configuration

**Reuse the current configuration structure and add an optional `models.text_gen.speculative` block.** Keep activation policy (`mode`) separate from decoding mechanism (`method`) and draft-model identity/source. The target remains selected by `vlm_name` and `weight_format`; no existing keys are renamed and no new top-level blocks are needed.

The example below retains every existing `models.text_gen` setting and its current value from [../../../config.yaml](../../../config.yaml), except for deliberately selecting Qwen3.8 and adding optional DFlash2. These speculative fields define the proposed contract, not settings already supported by the loader. Merge this subtree into the existing configuration, not replace the whole file. Omitting `speculative` preserves plain generation.

```yaml
models:
  text_gen:
    provider: vlm
    vlm_name: Qwen/Qwen3.8-27B
    device: GPU
    weight_format: int4
    max_new_tokens: 5120
    concurrency: 1
    queue_max: 8

    speculative:
      mode: auto
      method: dflash2
      draft_source: huggingface
      draft_model: z-lab/Qwen3.8-27B-DFlash2
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

| Configuration item | Upgrade behavior |
| --- | --- |
| Existing `provider`, `vlm_name`, `device`, `weight_format` | Keep names and meanings. For the new models use `provider: vlm`; select a listed model/precision combination. Keep an older installation's selection unless the operator changes it. |
| Existing `max_new_tokens`, `concurrency`, `queue_max` | Retain the configured generation and admission limits; the shown values remain 5120, 1 and 8. A larger model does not automatically increase these limits. |
| Existing `chunking` and `segmentation` | Preserve the nested structure and configured values. Validate context and memory budgets for the selected model; change tuning only when measurements justify it. |
| New optional `speculative` block | Select activation policy, method and draft artifacts without changing target or workflow settings. Defaults and validation are defined below. |

### Speculative Settings

| Field under `speculative` | Values and default | Purpose |
| --- | --- | --- |
| `mode` | `"off"` (default), `auto`, `"on"` | Disable acceleration, allow plain fallback, or require acceleration. This is not the algorithm name. |
| `method` | `auto` (default), `dflash`, `dflash2`, `mtp` | Select the decoding mechanism. `auto` selects the catalog's declared method, not trial-and-error loading. Future methods require an explicit supported profile. |
| `draft_source` | `null` (profile default), `huggingface`, `local`, `target` | Distinguish a Hub repository, an explicit local IR directory, and target-bundled MTP artifacts. Other sources require a supported adapter/profile. |
| `draft_model` | Repository ID or local directory; `null` selects the profile default | Identify the external drafter for DFlash/DFlash2. For MTP, leave null: use the target's prediction head, not a second model. |
| `draft_revision` | Immutable repository commit; `null` selects the profile's pinned revision | Reproduce a Hub download. Reject non-null values for `local` or `target`; bundled MTP inherits the target revision. |
| `num_assistant_tokens` | Positive integer; `null` selects the method/profile's tested default | Control the draft block size within the selected runtime's supported range. Do not reuse DFlash tuning for DFlash2/MTP without validation. |

| Selected target/method | Draft settings |
| --- | --- |
| Qwen3.6 INT4 with `dflash` | `draft_source: huggingface`, `draft_model: z-lab/Qwen3.6-35B-A3B-DFlash` |
| Qwen3.8 INT4/INT8 with `dflash2` | `draft_source: huggingface`, `draft_model: z-lab/Qwen3.8-27B-DFlash2` |
| Target with a qualified bundled `mtp` head | `draft_source: target`, `draft_model: null`; download required MTP files with the target |

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

Resolve defaults before download, then validate the complete target/method/source/revision combination against artifact metadata and the supported profile. An explicit method is never changed to another method on failure; `mode: auto` may fall back only to plain generation. Unknown methods, contradictory sources, mismatched drafters and out-of-range tuning fail validation rather than triggering fallback. In `"off"`, ignore dormant speculative fields and prepare only the target.

First-run profiles use website sources. `draft_source: local` requires a non-empty `draft_model` directory and a null `draft_revision`; it validates existing IR and never silently downloads a replacement when missing. Resolve relative local directories from the Smart Classroom root. `draft_source: target` is valid only with MTP and requires null `draft_model` and `draft_revision`. A source override or revision cannot bypass compatibility checks, enable arbitrary URLs or execute repository code. The manifest records resolved settings and actual artifact versions, including defaults.

**Do not add duplicate controls.** Automatic preparation still needs no `download` block. Target revisions, conversion recipes and dependency pins remain managed by the catalog. A `serving` block is not required to change models. Preserve feature flags, ASR/OCR/embedding settings, `content_search.vlm` and `grading.provider.vlm_provider`. Keep `models.model_hub` for target source selection; `draft_source` explicitly selects only the drafter source. Quote `"off"` and `"on"` in YAML to avoid boolean coercion. Older configurations and mode-only speculative configurations remain valid through defaults.

Tool definitions and selection are per-request API fields (`tools`, `tool_choice`, `parallel_tool_calls`), not new YAML settings or a separate service. Record tool/template capability in the model profile so unsupported requests fail before streaming; no `enable_tool_call` configuration flag is needed.

## 5. Model Preparation

Integrate preparation into [../../../start-smart-classroom.ps1](../../../start-smart-classroom.ps1), after configuration, proxy and software initialization and before model-dependent services start. Desktop and direct startup use the same helper; request handlers never download or convert files.

1. **Select:** Resolve the target and speculative policy, method and source. Validate explicit settings, then select the compatible catalog profile. A recognized method without runtime/profile support means plain generation in `auto` or an actionable failure in `"on"`.
2. **Prepare:** For Hub drafters, download pinned target/drafter files over HTTPS. For `local`, validate the specified IR directory without downloading a replacement drafter. For MTP, acquire the target's bundled head and metadata without downloading an unrelated external model. Use runtime-ready IR directly; convert downloaded sources only through the profile's qualified recipe. Network failures do not trigger unrelated export attempts.
3. **Validate:** Check required files, integrity, tokenizer/processor compatibility, runtime versions and target/drafter graph interfaces. Preserve the ordinary target if accelerated export needs separate IR. Record a manifest without overwriting active files or changing legacy model paths.
4. **Activate:** Load the resolved artifacts and run warm-up. Report readiness only after success; a completed download alone is not a ready model.

Create storage on demand, use resumable staging and per-artifact locks, and publish only complete validated artifacts. Bound retries and check disk space for weights and conversion intermediates. Keep prior valid artifacts for rollback. Legacy files can be validated and reused without claiming provenance that is not known.

### Launcher Behavior

| Invocation | Behavior |
| --- | --- |
| Normal startup | Download/prepare missing selected files, then start services under the failure policy below. |
| `-DownloadModelsOnly` | Prepare without changing services or running inference warm-up. Require all artifacts for the selected method: target plus external drafter, or target plus bundled MTP head. Return nonzero if incomplete, even in `auto`; this includes a missing accelerated profile. |
| `-SkipModelDownload` | Validate existing text-generation artifacts only; no network, conversion or dependency installation. An empty target cache fails. May combine with download-only to validate an offline bundle. |
| `-Silent` | No prompts; report outcome and exit status. It may restart existing services during normal startup, but never during download-only preparation. |

These are intended launcher behaviors; the preparation switches are part of the proposed change. Initialize proxy/environment settings before download-only dispatch, then exit before elevation, restart or cleanup. Reject download-only with desktop delegation or an externally owned server. Forward supported options through relaunch paths. Preparation requires no elevation and must not trigger service cleanup on failure.

Cache-only operation covers text generation, not ASR, embeddings, OCR/grading or frontend dependencies. Install trusted exporter dependencies during software setup. Validate paths and downloaded metadata, never execute repository code, and preserve TLS verification. Pass arguments as data and credentials/proxy settings through the environment without logging secrets.

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

The cache-only switch prevents acquisition even when files are missing; `local` draft sources also prohibit replacement downloads. Download-only requires every artifact for the requested method; a normal `auto` fallback is not successful accelerator qualification.

If native cleanup cannot be confirmed, stop the model process before recovery. Retain the plain-mode decision for that launch so recovery does not repeatedly activate a failing drafter. Never replay a partially streamed request. Roll back by restoring the previous model/artifacts or disabling speculation and restarting, not by deleting caches.

Health reports the target, tool-call capability, requested/effective method, drafter identity or target-bundled head, warm-up result and sanitized fallback reason. Detailed revisions, tuning and runtime versions remain available for diagnostics without exposing private local paths. Do not log sensitive tool arguments or results by default.

## 7. Release Decisions

| Area | Required checks |
| --- | --- |
| Backward compatibility | Load unchanged older configurations; retain existing key names, token/queue limits, chunking, segmentation and service endpoints. Test supported providers/model IDs, precisions and local paths; no drafter download when off; plain fallback in `auto`; no regressions from runtime dependency upgrades. |
| New model support | Qwen3.6 INT4 and Qwen3.8 INT4/INT8: empty-cache target/drafter download, required conversion, successful warm-up and later cache-only reuse. |
| Port-8000 tool calling | End-to-end function definition -> tool call -> tool result -> answer through `/v1/chat/completions`, with streaming and non-streaming clients. Test `none`/`auto`/`required`/named choices, multiple-call IDs, `parallel_tool_calls: false`, full history, malformed arguments, missing results, truncation, unsupported models and no server-side tool execution. |
| Speculative configuration | Missing/mode-only blocks, all supported methods, explicit/default Hub revisions, local path handling and tuning bounds. Reject cross-model drafters and MTP with an external draft source/model; bundled MTP must never trigger a z-lab download. |
| Classroom quality | Streaming/non-streaming text, images, supported thinking/structured output, cancellation and queue limits; summaries, mind maps, segmentation, reports, RAG Q&A, video summaries and grading. |
| Reliability | Invalid pairs and corrupt artifacts, network/disk failures, interrupted/concurrent downloads, safe startup fallback and non-disruptive download-only behavior on Windows PowerShell 5.1/7. |
| Performance | Repeated plain/accelerated comparisons: answer quality, time to first token, tokens/s, end-to-end p50/p95 latency and peak memory. Separate download/conversion/compile time from inference. |

Qualify the three new model/precision combinations on ARL and PTL with plain and paired DFlash/DFlash2 decoding: twelve configurations, plus older-model regression coverage. Include tool-call round trips in every tool-capable combination. Add a separate MTP case for every target/precision/platform that advertises a qualified bundled head; do not infer MTP support from DFlash2 results. CPU qualification is separate. Record artifact/runtime/driver versions and workload settings; a model name alone is not evidence of compatibility.

**Stakeholder approval:** retain existing defaults, require port-8000 tool-call qualification for the new Qwen profiles, make acceleration opt-in, and promote each method/profile only after agreed quality, latency and memory thresholds pass. Publish tested artifacts, conversion recipes and runtime versions before declaring DFlash2 or MTP support; no universal speedup is promised.