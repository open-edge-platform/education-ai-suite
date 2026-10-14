# Smart Classroom VLM/LLM Serving Design

## 1. Key Features and Compatibility

The upgrade expands model choice without changing how classroom applications access inference.

| Key feature | Stakeholder benefit |
| --- | --- |
| **Qwen3.5 / Qwen3.6 / Qwen3.8 model choice** | Qwen3.5-9B INT4/INT8, Qwen3.6-35B-A3B INT4 and Qwen3.8-27B INT4/INT8 through the shared OpenVINO service. |
| **Tool calling on port 8000** | OpenAI-compatible function calls and tool-result conversations through `/v1/chat/completions`, enabling agent workflows without a separate endpoint. |
| **Selectable speculative decoding** | Choose DFlash, DFlash2 or supported MTP explicitly, with plain-generation fallback under the `auto` activation policy. |
| **Automatic first-run preparation** | Download the target and required speculative artifacts, convert when needed, and reuse validated files on later starts. No pre-existing local model files are required. |
| **Backward compatibility** | Retain older models and configuration, the port-8000 API, `/v1/chat/completions`, and the shared classroom generation interface. |
| **Controlled activation** | Warm-up before readiness, visible acceleration status and safe failure handling before release. |
| **Workflow and model timing statistics** | Attribute processing time to ASR, VA, OCR, Summary, Mindmap and other stages, then compare individual model calls by model, precision, device and effective decoding method. |
| **Standalone `context_bench` benchmarking** | Compare model/runtime profiles using repeatable TTFT, TPOT, throughput and memory measurements, with optional retrieval-accuracy and generation-fidelity checks, without changing production settings. See [Chapter 8](#8-context-bench-implementation-design) for the implementation design and acceptance tests. |

**Older models remain supported**, including Qwen3-VL-8B-Instruct and Qwen3.5-9B. Preserve supported providers, model IDs, precisions, local paths and generation behavior. No configuration migration or default model replacement is required; speculation remains off unless enabled. A model without a qualified drafter can continue through plain generation. Software setup is a prerequisite, but manual model downloads or exports are not.

Keep one target per serving instance. Generating tool calls and consuming tool results are in scope; executing tools remains the client/controller's responsibility. Multi-model routing, UI redesign and NPU support are outside scope. Compatibility is a release requirement, not a claim that untested model/runtime combinations already work.

## 2. Model Profiles

| Model | Target artifacts | Optional accelerator |
| --- | --- | --- |
| Previously supported VLM/LLM models | Preserve their supported download/export paths and precisions | Plain generation; a drafter is not required |
| `Qwen/Qwen3.5-9B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.5-9B-int4-ov) or [INT8 IR](https://huggingface.co/OpenVINO/Qwen3.5-9B-int8-ov) | Plain generation; speculative decoding requires a separately qualified profile |
| `Qwen/Qwen3.6-35B-A3B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.6-35B-A3B-int4-ov) | [DFlash](https://huggingface.co/z-lab/Qwen3.6-35B-A3B-DFlash) |
| `Qwen/Qwen3.8-27B` | [INT4 IR](https://huggingface.co/OpenVINO/Qwen3.8-27B-int4-ov) or [INT8 IR](https://huggingface.co/OpenVINO/Qwen3.8-27B-int8-ov) | [DFlash2](https://huggingface.co/z-lab/Qwen3.8-27B-DFlash2) |

A Qwen3.5-9B selection uses `provider: vlm`, `vlm_name: Qwen/Qwen3.5-9B` and `weight_format: int4` or `int8` under `models.text_gen`. Omit `speculative` for plain generation; listing the target artifacts does not qualify a speculative method or tool-call capability.

A maintained catalog supplies compatible target/method combinations, default drafter sources, immutable revisions, conversion recipes, dependency versions and tested tuning values. Explicit speculative settings select or override these defaults only within a validated profile. Drafter precision is independent of target precision. Extend the catalog without restricting the existing plain-model loading path.

A source checkpoint is not runtime-ready IR. Each accelerated profile must provide downloadable compatible IR or a tested conversion recipe for downloaded source files, including target hidden-state outputs where needed. DFlash2 requires independent exporter/runtime qualification. MTP (multi-token prediction) uses the target's bundled prediction head and requires its own artifact/runtime qualification; it does not use either z-lab drafter above. Select one mechanism per pipeline, never silently substitute or combine them.

## 3. Architecture

Separate startup preparation from request handling. A shared helper prepares files once; the model owner loads and warms them before serving classroom requests.

![Startup and request flow for existing and new models](assets/vlm-llm-serving-overview.svg)

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

## 7. Processing-Time Statistics

Collect statistics at two levels: **workflow-stage elapsed time** for the classroom experience and **individual model-call time** for inference cost. These are nested measurements, not interchangeable values. This section defines the required reporting coverage; it does not claim that every timer is implemented. Qualification results for this checkout remain **pending measurement**; historical observations in the Section 8 reference are not measurements of this implementation.

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

For generation, define decode throughput as output tokens after the first token divided by seconds from first to last generated token; report it as unavailable when fewer than two tokens or no valid timestamps are available. Keep model TTFT distinct from client-visible TTFT, which also includes request preparation, queueing, transport and earlier map calls. Record durations locally within each process; do not subtract monotonic timestamps from different processes or hosts.

Use the following comparison matrix for the text-generation profiles. Expand each row by ARL/PTL, workload and effective method; include the existing installed model as the backward-compatibility baseline. Other ASR, VA, OCR, embedding and reranker models use the same per-call statistics with their actual configured identities.

| Target model | Precision | Decoding cases | Required timing summary per case | Measurement status |
| --- | --- | --- | --- | --- |
| `Qwen/Qwen3.5-9B` | INT4 | Plain | Call latency mean/p50/p95, TTFT, decode tokens/s | Pending |
| `Qwen/Qwen3.5-9B` | INT8 | Plain | Call latency mean/p50/p95, TTFT, decode tokens/s | Pending |
| `Qwen/Qwen3.6-35B-A3B` | INT4 | Plain; qualified DFlash | Call latency mean/p50/p95, TTFT, decode tokens/s | Pending |
| `Qwen/Qwen3.8-27B` | INT4 | Plain; qualified DFlash2 | Call latency mean/p50/p95, TTFT, decode tokens/s | Pending |
| `Qwen/Qwen3.8-27B` | INT8 | Plain; qualified DFlash2 | Call latency mean/p50/p95, TTFT, decode tokens/s | Pending |

### Collection and Reporting

Reuse existing timing sources while preserving their meanings: [ASR](../../../components/asr_component.py) writes `performance.transcription_time`; [Summary](../../../components/summarizer_component.py) writes `performance.summarizer_time`, `performance.summary_map_time`, `performance.ttft`, `performance.reduce_ttft` and `performance.tps`; [Report](../../../components/report_generator/report_generator.py) writes collection, generation and total times. These are component timers, not isolated model benchmarks. ASR includes upstream input waiting and optional diarization; the report generation timer also includes rendering/persistence. [Hardware monitoring](../../../monitoring/monitor.py) provides utilization, memory and power samples, not model-call latency. Keep these existing fields compatible and add the missing stage/call measurements at their owning boundaries.

Retain one record per stage attempt and model invocation so repeated calls, retries and failures are not overwritten by a last-value metric. Use monotonic clocks and finalize timers on success, failure or cancellation; for streaming, measure through generator completion, not generator creation. Separate client cancellation time from the end of any continuing native inference. Record status, counts and timing metadata only, with bounded retention; exclude prompts, transcripts, images, tool arguments/results, student identifiers, credentials and private paths.

For each stage and model group, publish successful sample count, total processing time, mean, min/max, p50 and p95, plus failed/cancelled attempt counts and their elapsed time separately. Mark skipped stages as not applicable and missing or unsupported measurements as unavailable, never zero. Treat existing negative sentinel values as unavailable. Preserve raw samples, units, measurement boundaries and the percentile calculation method; a single run is an observation, not a latency distribution.

Compare repeated warm runs using the same fixed inputs, prompt templates, token limits, chunking, concurrency, media settings and enabled stages. Publish hardware/driver/runtime/artifact versions, input durations or dimensions, token counts, warm-up/repetition counts, quality outcomes and an evidence link with every result. Separate isolated model benchmarks from concurrent classroom runs and cold-start measurements. Compute speedup only between matched plain/accelerated cases using the same latency statistic; report actual fallback as plain generation, not accelerated success.

## 8. Context Bench Implementation Design

### 8.1 Purpose and Reference Baseline

Implement `context_bench` as an offline, text-only OpenVINO LLM benchmarking tool. It answers whether a model can process a specified context within configured memory budgets, which runtime profile provides the best measured latency, and, optionally, how that profile affects retrieval accuracy and generation fidelity. It must not load the classroom application, start services, modify application configuration or automatically select production defaults. It benchmarks individual model calls; it does not replace the workflow-stage instrumentation in Section 7 or certify image handling and tool calling.

Use the supplied [implementation directory](https://github.com/tingjiec/edge-ai-suites/tree/validate-qwen3.6/education-ai-suite/smart-classroom/components/llm/context_bench) and [documentation directory](https://github.com/tingjiec/edge-ai-suites/tree/validate-qwen3.6/education-ai-suite/smart-classroom/docs/dev-guide/context-bench) as the porting reference. The reviewed snapshot is commit `8e73a032443f8be6d0cd273c353d79c94c0a7c7a`: [source](https://github.com/tingjiec/edge-ai-suites/tree/8e73a032443f8be6d0cd273c353d79c94c0a7c7a/education-ai-suite/smart-classroom/components/llm/context_bench), [design analysis](https://github.com/tingjiec/edge-ai-suites/blob/8e73a032443f8be6d0cd273c353d79c94c0a7c7a/education-ai-suite/smart-classroom/docs/dev-guide/context-bench/context_bench_design.md), and [usage guide](https://github.com/tingjiec/edge-ai-suites/blob/8e73a032443f8be6d0cd273c353d79c94c0a7c7a/education-ai-suite/smart-classroom/docs/dev-guide/context-bench/context_bench_guide.md). Resolve conflicting reference prose using that snapshot's executable code and configuration. Historical timings are workload-specific observations, not acceptance thresholds for this implementation.

**Reference behavior to retain:** named profile matrices, spawned trial isolation, one load per case, excluded warmup, repeated measurements, exact-length throughput prompts, optional accuracy probes, parent-side memory sampling/scoring, and incremental reporting. **Required integration changes** are explicitly identified below; they are not claims about features already available in this checkout. Do not reintroduce the older capacity-search/bisection tool or a dry-run mode that produces synthetic PASS results.

### 8.2 Modules and Ownership

Place the tool under `smart-classroom/components/llm/context_bench/`, its guides under `smart-classroom/docs/dev-guide/context-bench/`, and hardware-independent tests alongside the existing component tests. These are implementation destinations, not files added by this documentation change. Preserve the reference's small modules and lazy imports so configuration inspection and unit tests need neither OpenVINO nor model files.

| Module | Responsibility and implementation entry points |
| --- | --- |
| `benchmark.py` | CLI/config validation (`_parse_args`, `_load_settings`, `_resolve_profiles`), case planning, IR/cache preflight, sequential subprocess supervision, memory sampling, status evaluation, baseline matching and `write_report`. Own all run-level state and output files. |
| `trial_runner.py` | `run_case` loads the tokenizer/pipeline once, chooses throughput or accuracy execution, emits progress/results, and exits the child. Keep `_load_pipeline`, `prepare_pipeline_input`, `generation_config`, `read_perf_metrics`, `validate_mtp` and error classification independently testable. The reference's `mtp` argument is an internal normalized speculative descriptor for both MTP and DFlash. |
| `context_builder.py` | Render native chat templates, size synthetic transcript prompts, place accuracy inserts and count the actual inference input. Keep prompt construction outside measured generation. |
| `metrics.py` | Build iteration records, normalize units, compute throughput/speculative statistics and aggregate measured iterations. No runtime loading, report I/O or scoring dependencies. |
| `tasks.py` | Define `ProbeSpec`, task registry, deterministic planted values, questions and per-probe output budgets. |
| `scoring.py` | Pure scoring functions for retrieval, lexical overlap and token divergence; no model inference. |
| `accuracy.py` | Build probe sets, dispatch scoring, group results and pair generated answers with the selected baseline. Scoring runs in the parent after the timed call. |
| `wwb_adapter.py` | Optional, version-qualified who_what_benchmark semantic-similarity adapter. Missing package/model or unsupported result shape makes only similarity unavailable. |
| `dflash_draft_head.py` | Optional explicit preparation utility for a derived draft with its own quantized output head. Never run it implicitly inside a timed benchmark or overwrite serving artifacts. |
| Model-specific YAML and PowerShell launchers | Keep benchmark settings separate from application YAML. Provide model/precision profiles and the existing `run_benchmark.ps1` / `setup_env.ps1` entry-point pattern. |

The parent plans one throughput case per `(model, precision, device, context, task, profile)` and runs cases serially to avoid contaminating memory and timing with another benchmark. Accuracy uses one `(model, precision, device, context, profile)` case containing its probe set. Profiles do not share a live pipeline; iterations within one case do. A failed case must leave earlier measurements intact and must not prevent another independent case from running after child cleanup.

### 8.3 Configuration and CLI Contract

Load benchmark YAML with a safe parser into plain mappings, validate it, apply CLI overrides, then freeze a resolved settings snapshot before creating any child. Avoid importing an application configuration singleton merely to parse benchmark YAML. Precedence is **CLI override > selected benchmark YAML > documented tool default**. Resolve relative config arguments from the caller's directory, and model/cache/output paths from the Smart Classroom root; the launcher sets that working directory. Never write resolved values back to either YAML file.

| Section/key | Type and resolution rules |
| --- | --- |
| `model` | Required mapping: `provider: openvino`, non-empty `device`, `weight_format`, `models_base_path`; optional `model_dirs` mapping from benchmark model name to local IR directory. Support CPU/GPU device selectors, not NPU in this design. |
| `benchmark.models` | Required non-empty list of unique model names. These are benchmark keys, not necessarily Hub IDs. Resolve through `model_dirs` first; otherwise use `<models_base_path>/<provider>/<name with / replaced by _>_<weight_format>`. |
| `benchmark.context_tokens` | Required non-empty list of non-negative integers, sorted and deduplicated. Positive values are the total rendered input-token target, not transcript-only length. Zero means a standalone task prompt of its natural length. |
| `benchmark.output_tokens`, `warmup`, `iterations` | Required integers: output ceiling at least 2, warmup at least 0, measured iterations at least 1. Reject booleans as integers. Preserve the reference configurations' one warmup and three measured iterations; label zero-warmup/single-iteration runs as smoke tests. |
| `benchmark.throughput_task` | One task name or non-empty list; default `summary_2s`. Accept `summary_2s`, `classroom_summary`, `code`, `math`, `chat`; preserve order and deduplicate. |
| `benchmark.iteration_gap_sec` | Finite non-negative number, default 0. Intentional idle before each measured generation, excluded from generation time and the measured memory window. Report it as burst versus sustained workload metadata. |
| `benchmark.timeout_sec` | Required finite positive progress timeout, not a total case timeout. The pinned model configurations set 5400 seconds; this is not a universal TTFT requirement. Reject a gap greater than or equal to this timeout. |
| `benchmark.max_system_memory_pct` | Finite percentage in `(0, 100]`, tool default 80; the pinned configurations explicitly use 100. This is an evaluation budget, not an OS memory limit. |
| `benchmark.gpu_memory_budget_gb` | Required finite positive number for GPU runs, in GiB despite the legacy suffix. Operator-supplied platform budget; never derive a pass threshold from the driver's advertised total. CPU-only runs do not require GPU telemetry or enforce this budget. |
| `benchmark.cache_dir`, `output_dir` | Optional compiled-blob cache directory, default null; required output base directory. A cache must not enable prompt-prefix reuse. Record whether compiled artifacts were already cached. |
| `profiles` | Required non-empty list; each entry accepts only `name`, `ov`, `scheduler`, `mtp`, `dflash`. Names are unique non-empty strings; `ov` and `scheduler` are mappings. Reject misplaced `cache_size` at profile level. |
| `profile.ov` | OpenVINO/GenAI property mapping, preserved without speculative settings leaking into plugin properties. Unknown runtime properties produce `unsupported`, not silent removal. |
| `profile.scheduler` | Absent/empty selects stateful generation; a non-empty resolved mapping selects paged/continuous-batching generation. Require explicit positive `max_num_batched_tokens`, `max_num_seqs`, and boolean `enable_prefix_caching: false` on supplied paged profiles. |
| `profile.mtp` | Mapping with only `enabled`, `num_assistant_tokens`, `device`; a non-empty mapping implies enabled unless explicitly false. Preserve boolean shorthand only when an enabled profile receives its candidate count from the CLI. |
| `profile.dflash` | Mapping with only `enabled`, `model`, `num_assistant_tokens`, `device`; `model` is a required local draft IR directory when enabled. A profile cannot contain both `mtp` and `dflash`. |
| `accuracy` | Read only with `--accuracy`; accept `suites`, `baseline_profile`, integer `seed`, optional `embedding_model`, and the `retrieval`/`generation` mappings described in Section 8.6. Require an included baseline profile for generation-fidelity comparisons. |
| `speculative_reference` | Optional display-only metadata: `source`, positive `num_assistant_tokens`, and per-task `dataset`, positive `acceptance_length`, `speedup`, optional `throughput`. Published numbers never affect status or ranking. |
| `benchmark.record_text` | **Integration addition**, boolean, default false. Opt-in persistence of synthetic generated answers for offline rescoring/fork inspection; never enable for private classroom material. Scores and timings are retained regardless. |

**Required validation additions:** reject unknown benchmark/model keys and unknown task-option keys, non-finite numbers, malformed mappings and wrong scalar types rather than relying on Python truthiness. Preserve exact override semantics: `--pipeline-config KEY=VALUE` merges string values into every selected profile's `ov`; `--scheduler-config KEY=VALUE` converts only recognized boolean/numeric scalar values. `KEY=` removes a property. Validate the resulting configuration again. Warn if an override changes a stateful profile to paged; never silently restore a removed prefix-caching safeguard.

Normalize either speculative section to `{enabled, strategy, model, num_assistant_tokens, device}` inside the resolved profile, retaining the reference's internal `mtp` field name for the port. Disabled means `enabled: false` and null remaining fields; enabled `strategy` is `mtp` or `dflash`. `--mtp-tokens K` and its alias `--assistant-tokens K` change only already-enabled profiles, including DFlash, and must leave plain baselines plain. Benchmark profile settings are deliberately separate from the production `models.text_gen.speculative` policy: a requested accelerated case either runs that mechanism or reports failure, **never falls back to plain and keeps the accelerated label**.

Use this reduced Qwen3.6 example to implement and test the parser. Paths identify already-prepared artifacts; the 59 GiB GPU budget is an example for the reference machine, not a default for other platforms. This selects the stock draft explicitly, unlike the reference's derived-int4-head path.

```yaml
model:
  provider: openvino
  device: GPU
  weight_format: int4
  models_base_path: models
  model_dirs:
    Qwen3.6-35B-A3B: models/openvino/Qwen3.6-35B-A3B_int4

benchmark:
  models: [Qwen3.6-35B-A3B]
  context_tokens: [0, 8000]
  output_tokens: 512
  warmup: 1
  iterations: 3
  throughput_task: [code, math, chat, summary_2s]
  iteration_gap_sec: 0
  timeout_sec: 5400
  max_system_memory_pct: 80
  gpu_memory_budget_gb: 59
  cache_dir: null
  output_dir: monitoring/executionlogs/context_bench/qwen3.6_35b
  record_text: false

profiles:
  - name: paged_min
    ov: &qwen36_ov
      GPU_ENABLE_LARGE_ALLOCATIONS: "YES"
      KV_CACHE_PRECISION: f16
    scheduler: &qwen36_scheduler
      max_num_batched_tokens: 65536
      max_num_seqs: 1
      num_linear_attention_blocks: 17
      enable_prefix_caching: false
  - name: dflash_k7
    ov: *qwen36_ov
    scheduler: *qwen36_scheduler
    dflash:
      model: models/openvino/qwen3.6-35b-a3b-dflash-int4-ov
      device: GPU
      num_assistant_tokens: 7

accuracy:
  suites: [retrieval, generation]
  baseline_profile: paged_min
  seed: 20260917
  embedding_model: null
  retrieval:
    tasks: [niah_single]
    depths: [0.0, 0.5, 1.0]
    samples: 2
    output_tokens: 64
  generation:
    tasks: [summary, fact_sheet]
    samples: 2
    output_tokens: 256
    options:
      fact_sheet: {num_facts: 6}
```

`--list-profiles` prints the fully resolved matrix, model directories, effective pipeline mode, budgets, iteration plan and probe counts, then exits without importing inference dependencies, downloading, loading models or creating result files. The example plans **14 throughput cases**: two profiles times three standalone tasks plus four 8K tasks. With `--accuracy` it plans two 8K cases of ten probes each; context zero is excluded. An empty post-filter matrix is a configuration error, not a successful empty benchmark.

Preserve CLI options `--config`, `--models`, `--contexts`, `--profiles`, `--device`, `--weight-format`, `--output-tokens`, `--warmup`, `--iterations`, `--iteration-gap`, `--throughput-task`, `--output-dir`, the property overrides, candidate-count aliases, `--accuracy`, and `--accuracy-suites/tasks/depths/samples`. `--weight-format` changes a label and derived path, not the contents of an explicitly configured directory: require `model_dirs` to identify the matching IR and report its actual precision.

### 8.4 Artifact and Runtime Preflight

The benchmark consumes artifacts prepared by Section 5 or an explicitly operated export utility. Missing target IR is `missing_ir` with a model/profile-specific preparation hint; never download, export, install dependencies or repair model files during a timed run. Validate graph/weight pairs and tokenizer/detokenizer assets for the selected layout. Prefer `openvino_language_model.xml` for `VLMPipeline`; otherwise use `openvino_model.xml` for `LLMPipeline`. Check required files for that layout, not just whether one XML exists.

Read model architecture from `config.json`, including nested `text_config` for VLM exports. Read actual target/draft weight compression from IR metadata, not the directory name or YAML label. Record missing metadata as unknown; flag a precision-label mismatch and exclude it from a comparison claiming the requested precision. Dependency qualification covers the OpenVINO, GenAI, tokenizers, Transformers and exporter combination; a nightly snapshot observed in the reference is not a dependency pin for this repository.

| Case | Checks before loading |
| --- | --- |
| Plain | No external drafter or bundled head is passed to the constructor; fresh generation config has zero assistant tokens. Stateful profiles do not instantiate a scheduler. |
| MTP | Both `openvino_mtp_model.xml` and its BIN exist in the target directory; CPU/GPU target and draft use the same device; paged scheduler and `ATTENTION_BACKEND: PA` are required. Candidate count is a positive integer and `max_num_batched_tokens >= k + 1`. |
| DFlash | External draft graph/weights/config exist; target hidden-state outputs/locators and draft vocabulary match the qualified export. `dflash_config.target_layer_ids` is a non-empty list of unique non-negative integers within the target depth. With trained `block_size`, require `k <= block_size - 1`. |
| Hybrid DFlash scheduler | Use one live sequence for the supplied profiles. Require sufficient linear-attention rows: `num_linear_attention_blocks >= max_num_seqs + k + 1`; 17 covers the reference sweep through k=15. Keep the same scheduler reservation on the plain baseline. |
| All speculative cases | Greedy generation, one returned sequence, static `assistant_confidence_threshold = 0.0`, prefix caching disabled and a qualified runtime API. Reject unsupported combinations; no sampling or mechanism substitution. |

The reference calls `ov_genai.draft_model(draft_directory, device)` for both mechanisms: MTP uses the target directory, DFlash the external draft directory. Keep this dispatch in `_load_pipeline`. DFlash2 is **not implemented by the referenced DFlash adapter**; add it only after the separate exporter/runtime qualification required by Sections 2 and 6, not by relabeling a DFlash case.

**Required artifact-safety changes:** load local tokenizer data without `trust_remote_code`; do not print export instructions that enable remote code by default. The reference can backfill `hidden_states_decoder_layers` directly into target XML. Move that operation into explicit preparation on a separate derived artifact directory, using structured IR/XML APIs, complete validation and recorded source/output hashes. Likewise, `dflash_draft_head` must create a new directory tied to the exact target export, refuse an existing output and leave source files unchanged. Both operations are outside benchmark timing. Missing required metadata during benchmarking is an actionable preflight failure.

### 8.5 Execution and Child-Process Protocol

The resolved case is immutable, serializable data, not a model object. Keep runtime imports inside the child and use `multiprocessing.get_context("spawn")` on all supported platforms. Follow the order below:

1. Resolve/filter the entire run, validate profiles/probes, inspect local IR metadata and preflight fixed cache sizes across every context before the first load for that model. Create a unique run directory and an incomplete evidence snapshot.
2. For each `(model, context, task, profile)`, resolve any automatic cache size, validate the effective mode again, start the parent sampler and spawn one child. Record the pre-case memory baseline.
3. In the child, validate the case, load the local tokenizer and pipeline once, emit `loaded`, then build/validate the prompt. Record load and prompt-preparation durations separately from generation.
4. Run warmup and measured iterations on the same prompt and pipeline, resetting request state between calls. Use a fresh greedy `GenerationConfig`; set `apply_chat_template = false` because the prompt was already rendered. Warmup uses the full output ceiling, not the older four-token shortcut. Respect EOS in both warmup and measurements.
5. For a measured iteration, perform the configured idle gap first, emit `iteration_start`, then time `generate` through completion. Emit `prefilled` once on its first streamed token, followed by the completed iteration record. The streamer never truncates output to accelerate a case.
6. In accuracy mode, use the same child lifecycle but one prompt/output budget per probe. Warmup is unscored; `benchmark.iterations` does not multiply the probe set. The parent scores each completed probe and updates cross-profile comparisons when its baseline is available.
7. Send `done`, flush the result queue with `close` and `join_thread`, flush diagnostic streams, then use the reference's child-only `_post_and_exit` path to avoid unsafe native pipeline destructors. The parent joins the child before starting another case and checkpoints the result even on interruption.

| Event | Required payload beyond `event` and case ID | Parent action |
| --- | --- | --- |
| `device` | Optional driver memory total and capability diagnostics | Save descriptive metadata; do not replace the configured budget. |
| `loaded` | `load_time_s` | Mark load success and snapshot post-load memory while the child is alive. |
| `prompt` | Configured, HF and OpenVINO token counts; prompt hash | Mark `prompt_built`; save prompt identity without prompt content. |
| `iteration_start` | Unique iteration/probe index, `warmup` | Reset the iteration memory window; never reset case-wide peaks. |
| `prefilled` | Matching iteration/probe index | Mark first-token completion so a later failure is attributed to decode. |
| `iteration` | Throughput iteration record | Attach parent memory-window statistics, retain the raw sample and checkpoint. |
| `probe` | Iteration record plus `suite`, `task`, `depth`, `sample`, generated answer | Score against the parent-held truth; persist answer only under the text policy. |
| `done` | `load_ok`, last stage, accumulated records and optional classified error | Merge by record identity, avoiding duplication of already-streamed events; finalize the case. |

The reference's completed milestones are `start`, `loaded`, `prompt_built`, `prefilled`, `decoded`; failure attribution is respectively load, prompt construction, prefill, decode, decode. **Integration correction:** reset the per-iteration milestone before every generate, including warmup, so a later prefill timeout cannot inherit a prior iteration's `decoded` marker. Accuracy warmup must emit the same progress milestones. Track completed iterations separately from the active iteration.

Reset the progress deadline only for valid events from the active case. Timeout means no progress for `timeout_sec`, including potentially load, prompt building, prefill, decode or an intentional gap; it does not establish a hardware context ceiling. On normal `done`, allow a bounded join before termination. On timeout/Ctrl-C, terminate only the owned child, join, escalate to kill if needed, and refuse another case if process death cannot be confirmed. Drain already-queued results for a bounded interval before declaring `crashed`; keep partial iterations and last-stage evidence. Use `try/finally` for sampler, queue and process cleanup. Native crashes remain isolated from Python report state, but a subprocess does not protect the host from driver resets or system-wide memory exhaustion.

### 8.6 Prompt Construction and Accuracy

For positive-context throughput, render the selected tokenizer's native chat template once, including its generation prefix, and measure the complete rendered prompt. Subtract template/task overhead from the filler budget, construct a synthetic classroom transcript and correct the full-prompt token delta for at most five passes. Require `configured_tokens == HF_tokens == OpenVINO_tokens`; fail prompt construction if exact sizing cannot converge. For `LLMPipeline`, pass the counted `TokenizedInputs`; for `VLMPipeline`, pass the validated string without applying the template again.

Context zero is a sentinel, not a zero-token request: run `code`, `math` and `chat` using their standalone framing, require HF/OpenVINO counts to agree, and report the actual positive input length. Skip summary tasks and all accuracy suites at zero. At positive context, domain tasks follow the transcript. Keep task/prompt hashes in comparisons: changing the task changes draft acceptance and makes a different workload.

The optional `classroom_summary` task is a **read-only exception to standalone configuration**: resolve only the application's language, summary mode and prompt template, then freeze that request before the matrix starts. The branch reads a legacy inline prompt tree. For this checkout, use the current `load_prompt("summarizer", language, mode)` convention and reproduce the current summarizer's request/thinking policy without instantiating its component or ModelManager. Do not copy a legacy `/no_think` convention blindly. Record template/config hashes, and fail clearly if the requested prompt cannot be resolved. Other tasks must not depend on application configuration or real transcripts.

| Accuracy suite | Tasks and scoring contract |
| --- | --- |
| `retrieval` | `niah_single`, `niah_multikey`, `niah_multivalue`, `niah_multiquery`, `vt`, `cwe`, `fwe`, `qa`. Score planted-item recall for retrieval/tracing, set intersection-over-union for word aggregation, and any accepted answer for QA; also report normalized exact match, token F1 and distractor rate where applicable. |
| `generation` | `summary` and `fact_sheet`. Compare to the selected baseline's answer on the identical prompt: optional embedding similarity, ROUGE-1/2/L, chrF, first divergent token, normalized divergent tokens and byte-identical rate. Score `fact_sheet` coverage separately against planted facts. |

Each suite mapping accepts `tasks`, `depths`, `samples`, `output_tokens`, `options`. Defaults are retrieval depths `[0.0, 0.5, 1.0]`, two samples, 64 output tokens; generation depth `[0.5]`, two samples, 256 output tokens. Positive integer sample/output budgets and finite depths in `[0,1]` are mandatory. Only `niah_single`, `niah_multikey` and `qa` are depth-swept; other tasks distribute facts by construction. Per-case probe count is the sum over tasks of `samples * number_of_depths` for depth-swept tasks, otherwise `samples`. The full eight retrieval tasks plus two generation tasks produce 32 probes with these defaults.

Reuse `ProbeSpec` and the reference's task/scoring functions. Derive planted values deterministically from `(seed, context, task, depth, sample)` using stable hashing, not process-randomized Python hashes. Check that planted values do not occur in the filler. For multiple inserts, sort by depth and use cumulative filler allocation so rounding does not change total length; adjust filler only, never the facts. Aggregation-task ground truth must remain valid after filler truncation.

Unlike throughput, probes allow at most **16 tokens** deviation from the requested context for each tokenizer count; record both actual counts. An individual prompt-build failure creates an explicit skipped-probe record and processing continues; inference failure ends that child case. If the first probe cannot provide warmup, use the first buildable probe; if none can be built, report `no_output`. Report planned/completed/skipped counts and score denominators so missing probes cannot inflate an apparent accuracy pass. Honor each probe's decode ceiling and mark a reached ceiling as potentially truncated when the runtime cannot identify the finish reason.

Keep scoring out of timed generation. Pair fidelity results by model/artifact, context, prompt hash, suite/task/depth/sample and seed, not profile completion order; recompute idempotently after each case. Missing or failed baselines yield unavailable fidelity, not zero or a replacement baseline. Normalize only retrieval metrics with SQuAD-style article removal; ROUGE/chrF and lexical fallback must preserve articles. Use the model tokenizer for token divergence; label a reference-compatible word fallback explicitly and never compare word-unit values with token-unit values. Missing WWB must not disable other scores, and optional semantic scoring must run after all inference cases or release its resources before the next memory baseline.

These synthetic retrieval scores are not published RULER dataset scores, and similarity to a baseline is not absolute classroom-summary quality. Generated code is benchmark output, never executed. Throughput success alone is not accuracy success; fidelity self-comparison is a sanity check, not evidence of model quality.

### 8.7 Iteration Metrics and Comparison Rules

Retain the reference field names so existing metric consumers can be ported directly. Use milliseconds for latency, seconds for generation/load duration, tokens/second for throughput and GiB (`bytes / 1024^3`) for memory. Capture unrounded values for calculation and round only for presentation. Prefer each valid finite field from `DecodedResults.perf_metrics` independently; use streamer/wall-clock fallback only for compatible boundaries and record the source of each metric. **Integration correction:** unavailable tokenization, TTFT, TPOT and throughput values are null, not the reference's zero placeholders.

| Field | Definition |
| --- | --- |
| `input_size`, `output_size` | Actual consumed/generated token counts, preferring runtime counters. Keep configured context and pre-call tokenizer counts separately. If VLM retokenization differs, report it and group comparisons by actual input count; do not claim an exact-context result. |
| `generation_time` | `get_generate_duration()` converted from milliseconds to seconds, or elapsed time around `generate`. Excludes model load, external prompt construction, idle gap and scoring. |
| `first_token_latency` | Runtime `get_ttft()` or first streamer callback elapsed time, in ms. The derived prefill rate is a TTFT-based proxy, not an isolated kernel measurement. |
| `other_tokens_avg_latency` | Runtime `get_tpot()`; otherwise `(1000 * generation_time - first_token_latency) / (output_size - 1)` only for compatible clock boundaries, positive decode duration and more than one output token. |
| `latency` | `1000 * generation_time / output_size`, in ms/token; this includes prefill and is not TPOT. |
| `tokenization_time`, `detokenization_time` | Runtime-reported milliseconds or null; pre-rendering time is a separate host measurement. |
| `prefill_throughput` | `1000 * input_size / first_token_latency` when TTFT is positive. |
| `decode_throughput` | `1000 / other_tokens_avg_latency` when TPOT is positive. |
| `e2e_throughput` | `(input_size + output_size) / generation_time`; includes input work and must not be presented as output-token throughput. |
| `verification_steps`, `tokens_per_step` | Steps from the qualified runtime counter or guarded `raw_metrics.m_new_token_times` compatibility path. Acceptance length (AL) is `(output_size - 1) / (verification_steps - 1)`, excluding prefill; unavailable unless both exceed one. Plain generation should yield 1.00 when counts are available. |
| `mtp_draft_tokens`, `mtp_accepted_tokens`, `mtp_rejected_tokens`, `mtp_acceptance_rate` | Legacy names shared by MTP/DFlash. Prefer valid runtime counters/rate; DFlash may require `get_num_draft_processed_tokens()` when its draft count is zero. Derive rejected count as drafted minus accepted only for consistent counts. |
| `mtp_acceptance_estimated` | True only for a separately labeled `(AL - 1) / k` estimate when measured acceptance is unavailable. Never present this estimate as a runtime count or use it as a correctness threshold. Retain null when even a qualified estimate cannot be formed. |
| `mtp_draft_to_main_ratio` | Runtime draft/target inference-duration ratio. May include target prefill; not a per-decode-pass cost or an image-encoding speedup. |
| `first_decode_ms`, `steady_pass_ms`, `steady_tpot` | Use matching runtime per-pass duration/committed-token arrays. Convert raw microseconds to ms; exclude prefill, report the first decode pass separately, then median remaining pass duration and remaining total duration / committed tokens. Require at least two remaining passes. |
| `output_sha256`, `output_consistent` | Hash each generated answer; repeated-prompt hashes determine determinism. Different accuracy probes are not repeated-prompt trials, so their combined consistency is unavailable. |

Exclude every `warmup: true` record from timing aggregates. For each homogeneous case, retain sample count, median/p50, min/max and the Section 7 mean/total/p95 statistics; use nearest-rank p95 on sorted valid samples, and label fewer than 20 samples as insufficient for a stable tail estimate. Null values do not enter the denominator. Compute aggregate decode throughput from aggregate median TPOT, not the mean of reciprocals. A one-token EOS answer is a valid generated answer but has no TPOT and cannot enter the decode leaderboard.

Rank only complete, budget-measured `ok` cases with valid timing, using median TPOT ascending then TTFT ascending; print a separate fastest-TTFT result. Match speculative/plain pairs on target artifact/precision, actual prompt hash/count, device/platform/runtime, task, generation ceiling/greedy settings, warmup/iteration/gap plan and **fully resolved** `ov`/scheduler mappings. The draft mechanism/count is the changed variable. A stateful or differently quantized row is not the DFlash baseline. If auto sizing produces different scheduler settings, mark the comparison confounded and require an explicitly matched-pool rerun for isolated speculative speedup.

Report decode speedup as plain TPOT / speculative TPOT, total-call speedup separately as plain generation time / speculative generation time, and steady speedup from `steady_tpot` only when both have it. The speculative sweep includes k, AL, accepted fraction, pass ms and pass cost relative to a baseline step; AL/pass-cost is explanatory, not an independent measurement. Pick a best window per task, not by acceptance percentage alone. Warn on output forks or nondeterministic repetitions; a numerical speedup with differing outputs remains an observation, not a lossless-acceleration qualification. Never pool mixed accuracy-probe lengths into the repeated-prompt speedup leaderboard.

### 8.8 Memory Sampling and Cache Sizing

Reuse the parent-side `psutil.virtual_memory()` and Windows GPU-memory collector, sampled every 0.5 seconds by default. Never initialize an OpenVINO GPU context in the parent for metadata. Guard sampler/window updates with a lock. Missing counters remain null; retain sample coverage and the configured interval because sampled peaks can miss shorter spikes. Use system-wide labels: another application contributes to these counters, and shared GPU memory overlaps host RAM, so they must not be added together.

Case peaks cover load, warmup and all iterations. Measured iteration windows exclude load, warmup and idle; compute occupancy means as sum of `value * elapsed_time` divided by observed elapsed time, excluding intervals with missing readings. Aggregate the iteration means by median. A single instantaneous sample is labeled as such. Report minimum available host RAM as a diagnostic, not another pass threshold; post-load deltas are approximate and not measured KV allocation.

The configured budget governs status, while `gpu_budget_driver_gb` is descriptive only. Apply GPU checks only on GPU runs; CPU cases require host-RAM measurements. After confirmed child exit, allow up to 30 seconds for available RAM/GPU counters to return within 1 GiB of the pre-case baseline. If they do not settle, retain a warning and flag the next case as potentially contaminated; never use this wait as proof of native cleanup.

Cache sizing remains a preflight estimate, not capacity certification:

1. Compute growing KV bytes per token as `2 * full_attention_layers * kv_heads * (head_dim * element_bytes + quantization_overhead_per_row)`. Read top-level or `text_config` architecture; an inconsistent `layer_types` list yields unknown, not an underestimate. Use the actual supported KV precision and its quantization metadata.
2. Add fixed linear-attention state from unique IR state variables, multiplied by reserved sequence/linear-attention rows. Include decode growth up to the output ceiling, qualified MTP-head KV and DFlash state/verification reservations. The reference's target-context-only estimate is insufficient for long output or an unqualified external draft; unknown contributions must be reported explicitly.
3. `scheduler.cache_size` has three distinct forms: omitted means runtime-managed, a positive whole GiB value is fixed, and `auto` requests estimation. Validate every fixed pool against the known persistent requirement before loading. A stateful profile has no bounded scheduler pool.
4. For known demand, the reference heuristic is `needed = max(2, 1.3 * estimated_cache_gib) * pool_factor`; `ceiling = floor(gpu_budget_gib - weight_gib - 8)`; choose an integer pool between 2 GiB and that ceiling. Account for external draft weights. The reference's factor 2 for speculative pools is empirical, not a general MTP/DFlash rule; pin it only to profiles with evidence.
5. **Integration correction:** if the ceiling cannot fit the required pool, reject the planned case rather than silently clamp below demand and call it valid. If architecture, reservations or a CPU memory-budget mapping are unknown, report estimation unavailable and require an explicit/runtime-managed pool instead of guessing. Never let removal of an unresolved `auto` key silently change the requested pipeline mode.

Do not treat passing an estimated cache check as passing the measured peak-memory budgets. Keep fixed/cache-auto/runtime-managed configurations distinct in reports and compare the actual resolved settings.

### 8.9 Result Schema, Persistence and Status

Use versioned serializable mappings for IPC and persisted evidence; validate required fields at the parent boundary. Avoid sending runtime objects. The following defines the minimum schema; reference iteration names in Section 8.7 remain stable.

| Record | Required data |
| --- | --- |
| Run | `schema_version: 1`, unique `run_id`, tool commit, UTC start/end, `completed`, resolved configuration with exported paths redacted, source-config hash, environment/platform/runtime/driver versions, artifact identities/hashes, planned/completed/failed/skipped counts and warnings. |
| Case | `case_id`, model/artifact/precision, device, context, task/mode, profile, effective pipeline/speculative settings, requested/completed iteration or probe counts, status/error/stage, load/preparation time, raw iteration/probe records, aggregates, memory values and measurement availability. |
| Iteration | Case ID/index, warmup flag, prompt hash and counts, output count/hash, generation settings and finish/truncation state, Section 8.7 metrics with per-field source, parent memory-window values and coverage. |
| Probe | Iteration fields plus suite/task/depth/sample, deterministic fixture identity, status/skip reason, per-metric scores and scoring unit/version. Answer/truth text persistence follows `record_text`; transient answers are needed for scoring even when it is false. |
| Error | Stable category, completed milestone, active phase and sanitized explanation; raw native exit code when relevant. No credentials, private paths or prompt/answer excerpts in default diagnostics. |

Preserve the reference's `report.txt` as the single human-readable report and print the same rendered lines to the terminal. **Required integration addition:** write `results.json` as the machine-readable source of truth, including raw samples and provenance required by Section 7. The pinned reference writes only the text report and retains richer records in memory; it does not provide durable complete answers for offline rescoring.

Keep absolute artifact/cache paths in process memory only. In exported settings and diagnostics, use component-relative paths for component-owned files and opaque artifact IDs plus content hashes for external locations; omit user names, host names and credentials. Represent unavailable hardware/driver metadata as unknown rather than a guessed device name. The runner still uses the original resolved paths internally; redaction must not change which artifacts are loaded.

Create `<output_dir>/<UTC-timestamp>-<unique-suffix>/` exclusively to avoid same-second collisions. Initialize incomplete results before the first trial; checkpoint after each completed iteration/probe and case, and again in the run's `finally`. Write JSON and report through temporary files and atomic replacement; JSON is authoritative if report rendering fails, and both carry the same run ID/revision. Default text redaction applies to both sinks. `record_text: true` permits full synthetic answers in JSON and bounded escaped previews in the report; mark omitted/truncated previews clearly. Offline fidelity rescoring requires recorded answers, matching fixture/tokenizer versions and the baseline; otherwise only stored scores/timing can be reaggregated.

Report sections are: run metadata and completion/coverage; speed/resources per model/context/task; TPOT and TTFT winners; matched speculative-window sweeps and output-consistency warnings; retrieval per-task/depth tables and baseline deltas; generation fidelity/coverage; probe status/detail; failures and unavailable telemetry. Show all failed/budget-exceeded rows and their measured values without ranking them. Published reference results are a separately labeled comparison, never mixed into local samples. Do not silently auto-delete previous runs; keep each run bounded by the validated plan and configured output-token ceilings and make retention an operator choice.

| Status | Meaning and ranking consequence |
| --- | --- |
| `ok` | All planned measured work completed with required telemetry inside budgets. Eligible only for metrics that exist; not a semantic-quality verdict. |
| `memory_limit`, `gpu_memory_limit` | Inference completed but a measured budget was exceeded. Preserve timings and all exceeded-budget flags; exclude from rankings. |
| `measurement_error` | Inference completed but required RAM/GPU telemetry or measurement integrity is unavailable. Keep known values; exclude from rankings. |
| `partial` | **Integration addition:** only some planned iterations/probes completed, including prompt-build skips. Publish coverage and partial scores but exclude from full-run acceptance/rankings. A more specific runtime failure still takes precedence. |
| `oom` | Explicit allocation failure or scheduler cache-admission failure, not an inferred cause from high memory alone. |
| `gpu_abort` | Device command abort such as OpenCL -14; distinguish it from confirmed OOM. |
| `unsupported` | Requested property, mechanism, device or runtime capability is unsupported; not a hardware context ceiling. |
| `timeout`, `crashed` | Progress deadline elapsed or child died without a recoverable terminal result. Preserve partial data, native exit code and last milestone. |
| `no_output` | No successful measured output/probe; warmup alone does not count. |
| `load_error`, `error`, `missing_ir` | Other load/generation/orchestration failure or absent artifacts, with the phase and actionable sanitized reason. |

Choose status in this order: explicit runtime/artifact failure; no measured output; incomplete coverage; unavailable required measurement; GPU budget exceeded; host budget exceeded; otherwise `ok`. Preserve additional flags when more than one condition applies. Quality scores remain separate from execution status. `completed` means the planned matrix was processed, not that every case passed.

**CLI exit contract, an integration addition:** 0 for a valid plan-only invocation or a completed run with all required cases `ok`; 1 for completed runs containing failed/partial/unqualified cases or for orchestration/output-write failure; 2 for invalid arguments/configuration or missing required environment dependencies; 130 for Ctrl-C after best-effort checkpoint and child cleanup. Accuracy thresholds are not implicit exit-code gates. The reference does not make case failures a reliable nonzero CLI exit, so implement and test this deliberately; PowerShell must propagate the Python exit code.

### 8.10 Implementation Sequence and Verification

1. Port the pure settings/profile/prompt/metrics/scoring modules and five existing test families from the pinned reference. Keep public module entry points; isolate inference/WWB imports. Add the configuration and record contracts above before running models.
2. Port the plain child runner and parent sampler/supervisor. Implement lifecycle, null-metric, coverage, structured-output and exit-code corrections first; validate them with fake queues, clocks, samplers and processes.
3. Add Qwen3.5-9B INT4/INT8 plain benchmark configurations and port the reference Qwen3.6/Qwen3.8 configurations. The pinned Qwen3.6 matrix is INT4, paged baseline plus DFlash k=3/5/7/15, contexts 0/8000, 512-token ceiling and 30-second gaps. The pinned Qwen3.8 matrix is **INT8**, paged baseline plus MTP k=1/2/3/4/6, 8K context and 64-token ceiling. Provide separately identified INT4/INT8 artifact selections where required by Section 2; never assume a precision override converts existing IR.
4. Add qualified MTP/DFlash adapters and explicit derived-artifact preparation. Keep Qwen3.5 plain unless a separate speculative profile is qualified. Do not port DFlash2 as working functionality from a source that lacks it.
5. Add parent-side accuracy and optional WWB scoring, text-policy controls, launcher/docs, then run short hardware smoke tests before repeated and long-context matrices. Do not change the main application or its defaults as part of the benchmark port.

| Test family | Required checks |
| --- | --- |
| `test_context_bench_context_builder.py` | Template counted once; exact positive-context equality; standalone context zero; too-small budget/non-convergence; VLM runtime-count mismatch; multi-insert depth placement and the 16-token probe tolerance. |
| `test_context_bench_kv_estimate.py` | Hybrid/full-attention counting, nested VLM config, malformed metadata, quantized KV overhead, per-sequence/verification reservations, MTP and external-draft contributions, fixed-pool preflight, infeasible/unknown auto budget and no implicit backend change. |
| `test_context_bench_metrics.py` | Unit conversion, valid per-field runtime fallback, null/non-finite handling, EOS with zero/one/many tokens, warmup exclusion, nearest-rank percentiles, median TPOT reciprocal, AL excluding prefill, steady-pass minimums, matched-baseline filtering and missing-telemetry ranking. |
| `test_context_bench_trial_lifecycle.py` | Load once/build once for throughput; full-budget warmup; fresh request state; iteration milestones reset; event ordering/deduplication; partial records; terminal-result/exit race; timeout/Ctrl-C cleanup; native exit codes; blocked child; sampler-window synchronization; atomic checkpoints and CLI/launcher exit propagation. |
| `test_context_bench_accuracy.py` | Seed determinism, task/option validation, exact probe counts, truth surviving filler truncation, scorer golden cases and article handling, baseline-last ordering, prompt-hash mismatch, skipped-probe denominators, truncation flags, missing optional WWB, no generated-code execution and text redaction. |

Use deterministic metric fixtures: 101 input tokens, five output tokens, 0.3-second generation and 100-ms TTFT must produce 50-ms fallback TPOT, 20 decode tok/s, 1010 prefill tok/s and approximately 353.333 e2e tok/s. For 45 output tokens and 14 target passes, AL is `44/13`, not `45/14`. The reduced YAML example must resolve to 14 throughput cases or two accuracy cases with ten probes each, without any model load. Assert that importing/planning does not start application services, download files, execute remote code or modify input artifacts.

The following are acceptance commands **after the port exists**, run from the Smart Classroom root with the prepared benchmark-compatible environment. They are not commands implemented by this document update.

```powershell
python -m unittest discover -s components/tests -p "test_context_bench_*.py"
python -m components.llm.context_bench.benchmark --config components/llm/context_bench/config_qwen3.6_35b.yaml --list-profiles
python -m components.llm.context_bench.benchmark --config components/llm/context_bench/config_qwen3.6_35b.yaml --profiles paged_min dflash_k7 --contexts 8000 --throughput-task math --warmup 0 --iterations 1
python -m components.llm.context_bench.benchmark --config components/llm/context_bench/config_qwen3.6_35b.yaml --profiles paged_min dflash_k7 --contexts 8000 --accuracy --accuracy-tasks niah_single fact_sheet --accuracy-depths 0.5 --accuracy-samples 1
```

After smoke tests, restore at least one warmup and three measured iterations, run matched profiles across the intended context/task/precision/platform matrix, and collect separate sustained and gap-based results. For p95 qualification use enough repetitions to satisfy Section 8.7, not the three-sample initial comparison. Hardware acceptance also verifies artifact hashes unchanged, no orphan child processes, complete evidence after interruption, budget telemetry present and accuracy/output differences reviewed. Run on a dedicated evaluation host; memory-pressure benchmarks can affect the whole GPU/OS.

Preserve the PowerShell launcher's argument forwarding and explicit environment setup path, but keep `--list-profiles` free of dependency installation. Setup installs only reviewed pinned dependencies in the selected environment, not during a trial, and never weakens TLS or execution policy. Optional WWB package/model acquisition is explicit setup work. No HTTP benchmark service, production instrumentation refactor, automatic model switching or UI is required for this port.

## 9. Release Decisions

| Area | Required checks |
| --- | --- |
| Backward compatibility | Load unchanged older configurations; retain existing key names, token/queue limits, chunking, segmentation and service endpoints. Test supported providers/model IDs, precisions and local paths; no drafter download when off; plain fallback in `auto`; no regressions from runtime dependency upgrades. |
| Model/precision support | Qwen3.5-9B INT4/INT8: empty-cache target download, successful warm-up and later cache-only reuse without a drafter. Qwen3.6 INT4 and Qwen3.8 INT4/INT8: empty-cache target/drafter download, required conversion, successful warm-up and later cache-only reuse. |
| Port-8000 tool calling | End-to-end function definition -> tool call -> tool result -> answer through `/v1/chat/completions`, with streaming and non-streaming clients. Test `none`/`auto`/`required`/named choices, multiple-call IDs, `parallel_tool_calls: false`, full history, malformed arguments, missing results, truncation, unsupported models and no server-side tool execution. |
| Speculative configuration | Missing/mode-only blocks, all supported methods, explicit/default Hub revisions, local path handling and tuning bounds. Reject cross-model drafters and MTP with an external draft source/model; bundled MTP must never trigger a z-lab download. |
| Classroom quality | Streaming/non-streaming text, images, supported thinking/structured output, cancellation and queue limits; summaries, mind maps, segmentation, reports, RAG Q&A, video summaries and grading. |
| Reliability | Invalid pairs and corrupt artifacts, network/disk failures, interrupted/concurrent downloads, safe startup fallback and non-disruptive download-only behavior on Windows PowerShell 5.1/7. |
| Performance | Repeated plain/accelerated comparisons: answer quality, time to first token, tokens/s, end-to-end p50/p95 latency and peak memory. Separate download/conversion/compile time from inference. |
| Timing statistics | Publish stage and individual-model results defined in Section 7 for each qualification case. Verify attribution for shared models, overlapping stages, streaming completion, retries, failures, cancellation and skipped stages; retain raw samples and do not present unavailable timings as zero or pending cases as measured. |
| Context bench | Complete the Section 8 port and its hardware-independent tests; verify exact-context and matched-profile measurements, separate accuracy verdicts, interruption-safe evidence, nonzero failure exits and unchanged source/serving artifacts. Publish model-call evidence without presenting it as full classroom-workflow timing. |

Qualify Qwen3.5-9B INT4/INT8 on ARL and PTL with plain generation: four configurations. Qualify the three Qwen3.6/Qwen3.8 model/precision combinations on both platforms with plain and paired DFlash/DFlash2 decoding: twelve more configurations, for sixteen total, plus other older-model regression coverage. Include tool-call round trips in every tool-capable combination. Add a separate MTP case for every target/precision/platform that advertises a qualified bundled head; do not infer MTP support from DFlash2 results. CPU qualification is separate. Record artifact/runtime/driver versions and workload settings; a model name alone is not evidence of compatibility.