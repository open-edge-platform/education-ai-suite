# Smart Classroom First-Run Wizard Design

**Status:** Design approved. Phase 1 is in progress: the main-process flow, the network test and the setup plan are implemented; the wizard pages and the documentation changes are not yet.

## 1. Background

A validation run of the Windows desktop app found that the Python environment was not created after `start-desktop-app.ps1` finished, so the app needed manual intervention before it worked. The app expected the user to find the **Setup** screen and select **Fix**.

The interim fix makes the app prepare itself at launch:

- `SetupRunner.runAutomatic()` in [setup-runner.cjs](../../../Windows/ui/electron/services/setup-runner.cjs) runs every repair that needs neither administrator rights nor a confirmation, and the backend then starts.
- `--setup-only`, or `start-desktop-app.ps1 -SetupOnly`, runs the same preparation without a window. It exits with `0` (ready), `1` (failed, or the backend cannot start) or `2` (the backend can start, but administrator items remain).
- The window shows **Setup** while setup runs, and the backend cannot be started until setup finishes.

Four gaps remain, and this design closes them:

1. **Proxy.** Downloads start before the user can enter a proxy. Behind a proxy that the `HTTP_PROXY` and `HTTPS_PROXY` variables do not describe, the first run fails.
2. **Feature choices come too late.** Features decide which environments, models and prerequisites are needed, but they can only be changed after the downloads.
3. **Administrator steps are invisible.** Enabling Windows long paths and installing DL Streamer are left on the **Setup** screen, which a first-time user has no reason to open.
4. **No sense of time.** The longest parts, installing the Python packages and downloading models during the backend's first start, show no overall progress or expected duration.

## 2. Goals and Non-Goals

Goals:

- A user goes from the installer to a working **Home** screen without entering anything, on any network where the detected settings work.
- A user who wants to decide the proxy or the features can do so once, before anything large downloads.
- Long-running work shows honest progress, survives the window closing, keeps the PC awake and notifies the user when it ends.
- Failures name their cause and offer the next step.
- A user who has completed the wizard never sees it again.

Non-goals:

- Replacing the **Setup** and **Get started** screens. They remain the maintenance and expert views.
- Installing GPU or NPU drivers. They are checked and linked, as today.
- Offline installation.
- Changing what `--setup-only` does.

## 3. Constraints from Onboarding Validation

Releases are validated with the [onboarding-validation](../../../../.github/skills/onboarding-validation/SKILL.md) skill, whose agent works from a shell and cannot click through a window. The end-to-end runner in the `edge-ai-suites-tests` repository is unattended in the same way: its installer boot starts the installed app with `SC_AUTO_START_BACKEND=1` and waits up to 30 minutes for `/health`. These rules from [rules-onboarding-validation.md](../../../../.github/skills/onboarding-validation/references/rules-onboarding-validation.md) shape the design:

| Rule | Requirement | Consequence for the wizard |
| --- | --- | --- |
| 3.1 Zero config startup | Nothing may require input values to start; every parameter has a working default. | The recommended path starts on its own (Section 6.1). Every page has a working default. |
| 5.1 Three-step pattern | Install, start, verify, plus at most one automated preparation command. | The wizard is part of "start". `--setup-only` is the preparation command, and the wizard does not appear after it succeeds. |
| 5.4 No conditional branches | The get-started guide cannot say "if you are behind a proxy, ...". | Proxy detection moves into the app, and the guide's proxy note is removed. |
| 3.6 Automatic device selection | The default path never asks for an inference device. | The wizard asks no device questions. |
| 3.7 No token for the default model | Tokens are only for optional configurations. | The Hugging Face token appears only when the user turns on diarization, which is off by default. |
| 15.4 Specific error causes | Errors distinguish their causes. | Network and installation errors are classified (Sections 7.3 and 7.6). |
| 4.1 Full deploy under 5 minutes | Includes loading the models. | Not met today, because models download during the backend's first start. Phase 2 moves model preparation into setup (Section 11). |

## 4. Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D1 | The **Features** page ships in Phase 1. | Feature choices decide what downloads; asking afterwards wastes gigabytes. |
| D2 | DL Streamer is a video analytics prerequisite. Its setup step is enabled only while video analytics is effectively enabled. | Only video analytics uses it. Video analytics is on by default and rarely turned off, so most first runs still include DL Streamer. |
| D3 | A single administrator prompt is Phase 2. Phase 1 keeps the two existing prompts. | The single prompt needs a new elevated helper or installer work (Section 11). |
| D4 | The wizard can be skipped with **Set up manually**. | Administrators and experienced users may prefer the **Setup** screen. |
| D5 | Add vitest for renderer logic. | The wizard is the first piece of UI large enough to need tests. |
| D6 | The recommended path never waits indefinitely for input. It starts after a countdown; a failed network test or low disk space lengthens the countdown rather than stopping it; administrator prompts never hold up the queue. | Keeps the zero-click first launch that the interim fix introduced, for validation (rule 3.1) and for the CI runner. Added from Section 3. |
| D7 | The UI language defaults to the Windows display language. | Removes a question (rule 3.1). Added from Section 3. |

## 5. When the Wizard Appears

| At launch | Wizard |
| --- | --- |
| No first-run record, and the Python environment is not OK | Yes, from **Welcome**. |
| The record says the installation was in progress | Yes, resuming on **Install**. |
| The Python environment is OK: an upgrade from an earlier version, or `--setup-only` ran first | No. A completed record is written silently. |
| Completed record, and the environment was later deleted or broken | No. The automatic repair from the interim fix runs. |
| `--setup-only` | Never. |

The record holds onboarding facts only and never claims readiness. As [useReadiness.ts](../../../Windows/ui/src/services/useReadiness.ts) explains, a stored "setup complete" flag goes stale when the environment is deleted, upgraded or moved. Readiness stays derived from live checks.

The record is `state/first-run.json`:

```json
{
  "schema": 1,
  "stage": "welcome",
  "mode": "recommended",
  "completedAt": null
}
```

- `stage` is `welcome`, `customize`, `installing` or `done`.
- `mode` is `recommended`, `custom` or `manual`. While the Python environment has never been OK, a `manual` record turns off automatic setup at launch. Once the environment is OK, the user is treated like any other user who completed the wizard.
- The folder is `%LOCALAPPDATA%\SmartClassroom\state\` for the installed app, which already holds the shipped-configuration stamps, and `Windows\logs\state\` in a source checkout, which git ignores. A new `paths.stateDir()` returns it. It follows `paths.userDataDir()`, including the `SMART_CLASSROOM_USERDATA` override, so tests and CI can isolate it.
- An unreadable record is treated as missing, and the environment check decides.

The UI language choice is stored with the renderer's preferences rather than in the record. This also fixes the language resetting to English at every launch.

In `prepareAndStartBackend()` in [main.cjs](../../../Windows/ui/electron/main.cjs), the fast environment check gains one branch: when the environment is not OK and there is no completed record, the main process runs the checks and hands over to the wizard instead of calling `runAutomatic()`.

## 6. User Flow

```text
                    ┌───────────────────────── Customize ─────────────────────────┐
Launch ─► Welcome ──┤  This PC ─► Network ─► Features ─► Administrator tasks ─────┼─► Install ─► Done ─► Home
          checks,   │                                                             │
          network   └────────── countdown ends, or Install now ───────────────────┘
          test,
          countdown
```

The main process owns this flow as a state machine in a new `first-run.cjs`. The window displays it and sends the user's choices. A window that fails to load therefore cannot stall an unattended first run.

### 6.1 Recommended Path (Default)

1. **Welcome** runs the system checks and the network test with the detected settings, without any input.
2. When the test passes, a 15-second countdown starts: "Installing with recommended settings in 15 s". **Install now** skips the countdown. **Customize**, or any choice other than the language, stops it.
3. **Install** runs with the shipped defaults. Administrator tasks do not hold up the queue. They appear as a card: "Video analytics needs DL Streamer, which needs administrator approval. **Install now** / **Later**".

An unattended launch, such as a validation run, the CI runner or a user who walks away, therefore ends with a running backend, as it has since the interim fix. Anything that needs administrator approval stays listed on **Done** and **Get started**. When no wizard is on screen to show the countdown, because the window has not loaded or failed to, the installation starts as soon as the checks finish.

With `SC_AUTO_START_BACKEND=0` (`start-desktop-app.ps1 -NoAutoStart`) there is no countdown, and the wizard waits for a choice.

### 6.2 Customize Path

The user goes through **This PC**, **Network**, **Features** and **Administrator tasks**, then **Install**. Approval given on **Administrator tasks** puts those tasks first in the queue. The prompts then appear while the user is still at the screen, and the rest runs unattended.

### 6.3 When the Network Test Fails

**Welcome** opens **Network** with the failure, and the countdown lengthens to 60 seconds: "Trying anyway in 60 s". A user at the screen stops it by acting on the page, and fixes the proxy. An unattended launch tries anyway: if the network really is down, the installation fails with a classified error, exactly as it would today; if the test was wrong, it succeeds. **Try anyway** starts at once.

### 6.4 Set Up Manually

A link on **Welcome**. It writes a `manual` record and opens **Setup**. Nothing installs automatically (Section 5).

## 7. Pages

### 7.1 Welcome

- A header with the language selector. The default comes from `app.getLocale()`: `zh-*` selects Chinese, anything else English.
- What happens next, with the approximate download size and duration. Both are measured on the reference machine before release, not estimated.
- The checks and the network test start on arrival, followed by the countdown (Section 6.1).
- Actions: **Install now**, **Customize**, **Set up manually**.

### 7.2 This PC

- The results of the system and driver checks, grouped as ready, warnings (with links) and "will be installed".
- Nothing blocks: low memory, a non-recommended processor and older Windows builds only produce warnings today.
- One exception: free disk space below the 50 GB requirement is shown prominently, because running out of space mid-download is the hardest failure to recover from. On the recommended path it lengthens the countdown to 60 seconds, so that a user at the screen can stop it. Once stopped, installing needs **Continue anyway**.

### 7.3 Network

Proxy detection, in order:

1. The saved `.proxy-config`, written by `start-desktop-app.ps1` or the **Configuration** screen.
2. The `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` variables.
3. The Windows system proxy, including PAC scripts, from Electron's `session.resolveProxy()`. pip and the model downloads cannot read PAC scripts, which is why the result is written out explicitly.
4. A direct connection.

The test, in [network-probe.cjs](../../../Windows/ui/electron/services/network-probe.cjs), connects the way pip and the model downloads do: an HTTP `CONNECT` tunnel through the proxy, with basic credentials when the proxy URL carries them, then a TLS handshake checked against Node's bundled certificate authorities, which are close to the `certifi` bundle Python's downloaders use. Like pip, it uses the HTTPS proxy for these HTTPS hosts and does not fall back to the HTTP proxy, and it honors `NO_PROXY` by the same suffix rules. Each host gets a 10-second timeout, and the hosts are tested in parallel.

The candidates from the detection order are tried in turn, stopping at the first that reaches the Python package hosts, which every installation needs. Initial host list, to be confirmed with a traffic capture:

| Hosts | Used by |
| --- | --- |
| `pypi.org`, `files.pythonhosted.org` | Python packages |
| `cdn.winget.microsoft.com`, `www.python.org`, `github.com` | winget, the Python installer, FFmpeg |
| `github.com`, `objects.githubusercontent.com` | The DL Streamer installer, only while video analytics is enabled |
| `huggingface.co` or `modelscope.cn`, following `models.model_hub` | Models |

Each failure is reported by cause, from Node's error code, how far the connection got (to the proxy, through the tunnel, or the TLS handshake) and the proxy's reply. The mapping is unit-tested:

| Cause | Message gist |
| --- | --- |
| Host name not found | Check the network connection or the proxy address. |
| No answer within the timeout | A proxy may be required. |
| The proxy cannot be reached | The proxy address or port is wrong, or the proxy is down. |
| The proxy requires authentication | Enter the proxy as `http://user:password@host:port`. |
| Certificate error | The connection is being inspected; see Section 9. |
| Other HTTP error | The host and the status it returned. |

When `huggingface.co` fails and `modelscope.cn` succeeds, ModelScope is preselected as the model source. The Hugging Face mirror (`models.hf_endpoint`) is under **Advanced**.

**Continue** writes `.proxy-config` and `models.model_hub` through the existing `config:apply` path and its validation. On the recommended path, a detected configuration that passed the test is saved without asking, with `NO_PROXY` set to `localhost,127.0.0.1` when it is empty, because the backend calls its own services on the loopback address. A saved proxy that failed where a direct connection worked is cleared, or every download would keep trying it. Proxy credentials never reach the window unmasked.

### 7.4 Features

Features are grouped by what the user does, with their ids from [feature-catalog.cjs](../../../Windows/ui/electron/services/feature-catalog.cjs):

| Group | Features | Adds |
| --- | --- | --- |
| Classroom recording | `asr`, `summary`, `mindmap`, `topic_segmentation`, `report` | Speech recognition and text generation models |
| Video analytics | `video_analytics`, `board_ocr` | DL Streamer (administrator approval) and video models |
| Content search | `content_search`, `qa` | Content search models and services |
| Grading | `grading` | The grading conversion environment and the layout detection model |

- The defaults are the shipped `config.yaml`: everything on except grading.
- The page applies the dependency rules that `config:validate` already enforces, so it cannot save a combination the backend would undo at startup. For example, `report` depends on `video_analytics`, so turning off video analytics while keeping the report is offered as a fix rather than saved silently.
- Settings shown come from the fields marked `wizard: true` in [config-schema.cjs](../../../Windows/ui/electron/services/config-schema.cjs), rendered with the existing `ConfigFieldControl`. Device fields are excluded (rule 3.6), and the proxy fields are on **Network**. In practice that leaves the speech recognition provider and model, and diarization with its Hugging Face token, which appears only when diarization is on (rule 3.7). When the UI is in Chinese, `funasr` with `paraformer-zh` is suggested but not forced.
- Changes save to `config.yaml` through `config:apply`. They can still be made after the installation has started: steps that have not run yet follow the new choice, because `config:apply` already re-checks newly enabled setup steps.

For D2, the DL Streamer step uses the same "effectively enabled" rule as `effectivelyEnabled()` in [registry.cjs](../../../Windows/ui/electron/services/registry.cjs). A feature that depends on video analytics, such as `board_ocr` or `report`, therefore keeps DL Streamer required, because the backend enables video analytics for it at startup.

### 7.5 Administrator Tasks

Shown only when needed: Windows long paths are disabled, or DL Streamer is missing or outdated while video analytics is effectively enabled.

- Each task says what it does, what it unlocks and that Windows will ask for approval.
- **Run** records approval and puts the tasks first in the queue. **Skip** leaves them listed on **Done** and **Get started**.
- Phase 1 uses the two existing actions, so the user approves two prompts: one for long paths and one for the DL Streamer installer. Phase 2 reduces this to one (D3).

### 7.6 Install

```text
┌ Smart Classroom setup ─────────────────────────────────────────────┐
│ ✓ Welcome    Installing                              Step 3 of 7   │
│ ✓ This PC    ✓ Administrator tasks (long paths, DL Streamer)  2:10 │
│ ✓ Network    ✓ Python 3.12                                    0:42 │
│ ✓ Features   ● Python environment                            12:05 │
│ ✓ Admin        Downloading openvino-2026.2.1-cp312-...  (98 MB)    │
│ ● Install    ○ Grading conversion environment                      │
│ ○ Done       ○ Layout detection model                              │
│              ○ First start: download AI models                     │
│                                                                    │
│ You can leave this running. Your PC stays awake until it finishes. │
│ [Show details]                                        [Cancel]     │
└────────────────────────────────────────────────────────────────────┘
```

- **Queue.** It comes from a new `SetupRunner.plan()`, which `runAutomatic()` uses too, so the page lists exactly what will run. The last item is the backend's first start. It names the model being downloaded by reading the `Downloading {repo}@{revision} from ...` line that `download_snapshot()` in [model_download_helper.py](../../../Windows/utils/model_download_helper.py) logs for every model download.
- **Progress.** A step counter, the elapsed time per step and the current output line, with the full log under **Show details**. No percentages until there is data to base them on (Phase 2).
- **Running unattended.** The PC is kept awake with `powerSaveBlocker` (`prevent-app-suspension`). Progress shows on the taskbar icon (`setProgressBar()`), and a Windows notification announces the end or a failure.
- **Interruptions.** Closing the window asks for confirmation; it stops the current step, and the next launch resumes on **Install** without asking again. **Cancel** stops the queue and offers **Resume**.
- **Failures.** The failed step expands with its classified cause (network, certificate, disk full, files in use, other) and these actions: **Retry**, **Back to Network** for network causes, **Copy diagnostics** and **Open Setup**.

### 7.7 Done

- What was installed, and what was skipped or failed, with the features each one affects.
- **Open Smart Classroom** goes to **Home** once the backend is healthy.
- Writes the completed record.

## 8. Architecture

### 8.1 Main Process

| Module | Change |
| --- | --- |
| `main.cjs` | The wizard branch in `prepareAndStartBackend()`. Keep-awake, taskbar progress, notification, and the close confirmation during installation. |
| `first-run.cjs` (new) | Reads and writes the record. A pure `needsWizard()` implementing Section 5, and the flow of Section 6 as a pure state machine (`next(state, event)`) that owns the countdown. |
| `network-probe.cjs` (new) | `candidates()` and `parseSystemRule()` for detection, `probeHost()` and `probeCandidate()` for the test, `classify()`, `evaluate()` for whether the recommended settings work, and `recommendedChanges()` for what the recommended path writes. |
| `setup-runner.cjs` | `plan()` returns the ordered `{ stepId, actionId, kind }` entries, where `kind` is `auto`, `elevated` or `manual`. `runAutomatic({ includeElevated })` puts approved elevated tasks first. The DL Streamer step is enabled only while video analytics is effectively enabled (D2). |
| `registry.cjs` | Exports `effectivelyEnabled()` for the setup runner. |
| `paths.cjs` | `stateDir()`. |
| `ipc.cjs`, `preload.cjs` | The channels below. |

New IPC channels follow the existing rules in [ipc.cjs](../../../Windows/ui/electron/services/ipc.cjs): the sender must be the app's own window, and the renderer passes ids and values, never commands or paths.

| Channel | Purpose |
| --- | --- |
| `firstRun:get`, `firstRun:changed` (event) | The flow state, including the detection and test results with credentials masked, and the record. |
| `firstRun:attach` | A wizard is on screen, so the flow may show a countdown. |
| `firstRun:send` | A user choice: `customize`, `installNow` (with `includeElevated`), `approveElevated` or `manual`. **Try anyway**, **Continue anyway**, **Retry** and **Resume** are all `installNow`; skipping the administrator tasks is not approving them. |
| `network:probe` | The **Network** page's test of typed values, validated by the Configuration screen's rules first. |
| `setup:plan` | The **Install** queue. |

### 8.2 Renderer

- A new `components/FirstRun/` folder: `FirstRunWizard` as the shell, with the step list and window controls but no app navigation, and one component per page.
- [App.tsx](../../../Windows/ui/src/App.tsx) shows the wizard instead of the app while `needsWizard()` holds. The existing first-run screen logic stays for users who completed the wizard.
- Reuses `useSetup`, `useSetupLogs`, `useConfig`, `ConfigFieldControl` and `useServices`.
- All strings go in `en.json` and `zh.json`.
- Each page moves focus to its heading, and progress is announced through an `aria-live` region.

### 8.3 Tests

- `node --test`, as today: `needsWizard()`, the flow state machine including the countdown and every interrupting choice, `plan()` order and kinds, the DL Streamer rule, error classification with a stubbed fetch, and reading a missing or unreadable record.
- vitest, new (D5): renderer logic kept in plain modules, such as page order and credential masking.
- Manual, on clean virtual machines: a direct connection, an explicit proxy, a PAC proxy, a proxy requiring authentication, Hugging Face blocked, cancel and resume, closing during installation, declining an administrator prompt, an upgrade from the previous release (no wizard expected), `--setup-only` before the first launch, and an unattended launch that must end with a healthy backend.
- CI lives in the separate `edge-ai-suites-tests` repository. Its `unit-integration` workflow runs pytest only, so neither `test:electron` nor vitest runs in CI today. Adding both there is a follow-up.
- Its end-to-end installer boot reuses a provisioned user-data folder, where the Python environment is OK, so the wizard never appears there (Section 5). Covering the unattended first launch (Section 6.1) needs a case with an empty user-data folder, for example by pointing `SMART_CLASSROOM_USERDATA` at a new folder. The full first run then has to fit the runner's 30-minute health timeout, which suits a nightly schedule rather than every run.

## 9. Failure Handling and Edge Cases

| Situation | Behavior |
| --- | --- |
| The network test fails for every host | **Network** shows each cause, with a 60-second countdown to trying anyway. |
| Only Hugging Face is blocked | ModelScope is preselected. |
| HTTPS inspection on the network | The test checks certificates against a list close to Python's `certifi`, so it fails with a certificate error where the model downloads would. A tool that trusts the Windows certificate store can still succeed where the test failed; the failure only lengthens the countdown (Section 6.3). **Install** also recognizes certificate errors and explains them. |
| The PAC script returns different proxies per host | The proxy for `pypi.org` is saved, and the test shows any host it fails for. |
| Free disk space below 50 GB | A 60-second countdown, with the warning shown. Once a user stops it, **Continue anyway** is required. |
| An administrator prompt is declined | The task is marked skipped and listed on **Done** and **Get started**. |
| The window is closed during installation | Confirmation, then the next launch resumes. |
| The app is closed during the countdown | Nothing started. The next launch shows **Welcome** again. |
| A backend is already running, for example started from PowerShell | The environment is OK, so no wizard. |
| Several Windows users on one PC | The record is per user, so each user sees the wizard once. |
| No network at all | Out of scope. **Network** explains that the installation needs a connection. |

## 10. Documentation Changes

- [Get Started on Windows](../../user-guide/get-started/get-started-windows.md): Step 3 describes the wizard and its recommended path, the proxy note goes (rule 5.4), and the administrator approval is described where it appears.
- The same guide documents `--setup-only` as the single preparation command for unattended installs (rule 5.1).
- [ui/README.md](../../../Windows/ui/README.md): the wizard, the first-run record and how to reset it for testing.
- `start-desktop-app.ps1`: its first-launch message describes the wizard and the countdown.

## 11. Phases

| Phase | Scope | Size |
| --- | --- | --- |
| 1 | Sections 5 to 10: the record and the wizard branch, every page, proxy detection and the connection test, the model source suggestion, the DL Streamer rule (D2), `plan()` and `runAutomatic({ includeElevated })`, progress, resume, keep-awake, taskbar progress, notification, vitest. Administrator tasks use the two existing prompts. | M to L |
| 2 | **A single administrator prompt (D3).** Two options to evaluate in a spike: (a) an elevated helper started by the app that performs both tasks and writes a log the app follows, with the DL Streamer installer downloaded before elevation, which needs a download-only mode in [check_dlstreamer.ps1](../../../Windows/Scripts/check_dlstreamer.ps1); (b) both tasks in the NSIS installer, where users expect a prompt and per-machine installs already run elevated. Option (b) removes prompts from the first launch entirely, but the installer would need the DL Streamer installer bundled or downloaded, and a proxy. **Model preparation as a setup step.** A backend entry point that downloads the models of the enabled features without starting the server, run by **Install** and by `--setup-only`. The first launch then only loads models (rule 4.1), and downloads can report real progress, for example through the `tqdm_class` parameter of `huggingface_hub.snapshot_download()`; the ModelScope equivalent is to be verified. | M |
| 3 | A `uv`-based bootstrap: no winget or preinstalled Python, and faster package installs. | L |

## 12. Open Items

- Measure the download sizes and durations shown on **Welcome** and on each **Install** step on the reference machine.
- Confirm the host list in Section 7.3 with a traffic capture.
- In `edge-ai-suites-tests`: run `test:electron` and vitest in the `unit-integration` workflow, and add the unattended first-launch case (Section 8.3).
