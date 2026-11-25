# Smart Classroom First-Run Wizard Design

**Status:** Design approved. Phase 1 and Sections 13 and 14 are implemented, except for the user-guide changes in Section 10. Of Phase 2, the single administrator prompt (D3) and byte-level download progress (Section 8.4) are implemented. Model preparation as a setup step was set aside; instead, **Done** explains a failed first start (Section 11).

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

- Replacing the **Setup** screen. After the first run, it is where problems are fixed (Section 14).
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
| 4.1 Full deploy under 5 minutes | Includes loading the models. | Not met, because models download during the backend's first start. Moving that into setup was set aside (Section 11). |

## 4. Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| D1 | The **Features** page ships in Phase 1. | Feature choices decide what downloads; asking afterwards wastes gigabytes. |
| D2 | DL Streamer is a video analytics prerequisite. Its setup step is enabled only while video analytics is effectively enabled. | Only video analytics uses it. Video analytics is on by default and rarely turned off, so most first runs still include DL Streamer. |
| D3 | One administrator prompt for all administrator tasks: the app starts one elevated helper that runs them all (Section 7.5). Phase 1 kept the two existing prompts. | Two prompts for one setup read as two separate requests. A helper the app starts also covers per-user installs and source checkouts, and runs after the feature choice that decides whether DL Streamer is needed; the NSIS installer could do neither (Section 11). |
| D4 | The wizard can be skipped with **Set up manually**. | Administrators and experienced users may prefer the **Setup** screen. |
| D5 | Add vitest for renderer logic. | The wizard is the first piece of UI large enough to need tests. |
| D6 | The recommended path never waits indefinitely for input when the checks pass. It starts after a countdown, and administrator prompts never hold up the queue. A failed network test or low disk space stops the flow instead (Sections 6.3 and 7.1): an installation without its downloads can only fail, and one that fills the disk is the hardest failure to recover from. | Keeps the zero-click first launch that the interim fix introduced, for validation (rule 3.1) and for the CI runner. Added from Section 3. |
| D7 | The UI language defaults to the Windows display language. | Removes a question (rule 3.1). Added from Section 3. |
| D8 | After the first run, the wizard stays as the **Setup assistant** in review mode and replaces the Get started screen (Section 13). Superseded by D11. | The first run and every later visit answer the same question with the same pages. |
| D9 | Features are chosen by group everywhere, each group a section with its features and settings always shown. | One way to choose features, in the assistant and on the Configuration screen. |
| D10 | The assistant and the Setup, Configuration and Services screens share one set of UI parts (Section 13). | One look, fixed in one place. |
| D11 | After the first run, the **Setup** screen is the one place for what is not working: only the problems, one **Fix**, and every check below them. The review mode is removed, and the wizard, now first-run only, loses **This PC** (Section 14). | Developers found three pages about something not being installed, and the review mode hard to navigate. A list of problems with one button is simpler than the old Get started screen. |

## 5. When the Wizard Appears

| At launch | Wizard |
| --- | --- |
| No first-run record, and the Python environment is not OK | Yes, from **Welcome**. |
| The record says the installation was in progress | Yes, resuming on **Install**. |
| The Python environment is OK: an upgrade from an earlier version, or `--setup-only` ran first | No. A completed record is written silently. |
| Completed record, and the environment was later deleted or broken | No. The automatic repair from the interim fix runs. |
| `--setup-only` | Never. |

The record holds onboarding facts only and never claims readiness: a stored "setup complete" flag goes stale when the environment is deleted, upgraded or moved. Readiness stays derived from live checks, as on the **Setup** screen (Section 14).

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

The UI language choice is stored by the main process in `state/preferences.json`, not in the record, and the preload reads it synchronously so the first render is already in the right language. It cannot live in the renderer's `localStorage`: the packaged UI is served from a new loopback port at every launch, and storage belongs to the origin, port included. This also fixes the language resetting to English at every launch.

In `prepareAndStartBackend()` in [main.cjs](../../../Windows/ui/electron/main.cjs), the fast environment check gains one branch: when the environment is not OK and there is no completed record, the main process runs the checks and hands over to the wizard instead of calling `runAutomatic()`.

## 6. User Flow

```text
                    ┌──────────────────── Customize ────────────────────┐
Launch ─► Welcome ──┤  Network ─► Features ─► Administrator tasks ──────┼─► Install ─► Done ─► Home
          checks,   │                                                   │
          network   └────────── countdown ends, or Install now ─────────┘
          test,
          countdown
```

The main process owns this flow as a state machine in a new `first-run.cjs`, countdown included. The window displays it and sends the user's choices. A window that fails to load therefore cannot stall an unattended first run.

### 6.1 Recommended Path (Default)

1. **Welcome** runs the system checks and the network test with the detected settings, without any input.
2. When the test passes, a 15-second countdown starts: "Installing with recommended settings in 15 s". **Install now** skips the countdown. **Customize**, or any choice other than the language, stops it.
3. **Install** runs with the shipped defaults. Administrator tasks do not hold up the queue. They appear as a card: "Video analytics needs DL Streamer, which needs administrator approval. **Install now** / **Later**".

An unattended launch, such as a validation run, the CI runner or a user who walks away, therefore ends with a running backend, as it has since the interim fix, provided the network test passes and the disk has room. Anything that needs administrator approval stays listed on **Done** and on the **Setup** screen. The countdown runs in the main process, so it ends, and the installation starts, even when the window never loaded.

With `SC_AUTO_START_BACKEND=0` (`start-desktop-app.ps1 -NoAutoStart`) there is no countdown, and the wizard waits for a choice.

### 6.2 Customize Path

The user goes through **Network**, **Features** and **Administrator tasks**, then **Install**. Approval given on **Administrator tasks** puts those tasks first in the queue. Windows then asks for approval, once, while the user is still at the screen, and the rest runs unattended.

### 6.3 When the Network Test Fails

The flow stops, with no countdown, and **Network** opens with the failure: "Setup could not reach the download hosts, so it has not started installing. Fix the proxy below, then continue." The same applies when the test could not run at all. The user fixes the proxy, tests it on the page, and goes on through **Features** to **Install**, as when customizing; **Back** and **Welcome**'s **Install now** remain, for a user who knows the test was wrong. An unattended launch therefore waits for someone, rather than starting an installation that would fail on its first download. With automatic start off the network page shows too, since the network is what needs attention.

### 6.4 Set Up Manually

A link on **Welcome**. It writes a `manual` record and opens **Setup**. Nothing installs automatically (Section 5).

## 7. Pages

### 7.1 Welcome

- A header with the language selector. The default comes from `app.getLocale()`: `zh-*` selects Chinese, anything else English.
- What happens next, with the approximate download size and duration. Both are measured on the reference machine before release, not estimated.
- The checks and the network test start on arrival, followed by the countdown (Section 6.1).
- Actions: **Install now**, **Customize**, **Set up manually**.
- Nothing in the checks blocks: low memory, a non-recommended processor and older Windows builds only produce warnings.
- One exception: free disk space below the 50 GB requirement is shown prominently, because running out of space mid-download is the hardest failure to recover from. It stops the flow, with no countdown, on **Welcome**: installing needs **Continue anyway**, there or on the page whose button installs. An unattended launch therefore waits for someone.

### 7.2 This PC

Removed (D11). **Welcome** shows the result of the checks, and the full list is under **All checks** on the **Setup** screen.

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

- Each group is a section, divided from the next by a rule. Its heading has a checkbox that turns the whole group on or off (mixed when only some of its features are on), and its features and settings are always shown below it.
- The defaults are the shipped `config.yaml`: everything on except grading.
- The page applies the dependency rules that `config:validate` already enforces, so it cannot save a combination the backend would undo at startup. For example, `report` depends on `video_analytics`, so turning off video analytics while keeping the report is offered as a fix rather than saved silently.
- Settings shown come from the fields marked `wizard: true` in [config-schema.cjs](../../../Windows/ui/electron/services/config-schema.cjs), rendered with the existing `ConfigFieldControl`. Device fields are excluded (rule 3.6), and the proxy fields are on **Network**. In practice that leaves the speech recognition provider and model, and diarization with its Hugging Face token, which appears only when diarization is on (rule 3.7). When the UI is in Chinese, `funasr` with `paraformer-zh` is suggested but not forced.
- Changes save to `config.yaml` through `config:apply`. They can still be made after the installation has started: steps that have not run yet follow the new choice, because `config:apply` already re-checks newly enabled setup steps.

For D2, the DL Streamer step uses the same "effectively enabled" rule as `effectivelyEnabled()` in [registry.cjs](../../../Windows/ui/electron/services/registry.cjs). A feature that depends on video analytics, such as `board_ocr` or `report`, therefore keeps DL Streamer required, because the backend enables video analytics for it at startup.

### 7.5 Administrator Tasks

Shown only when needed: Windows long paths are disabled, or DL Streamer is missing or outdated while video analytics is effectively enabled.

- Each task says what it does, what it unlocks and that Windows will ask for approval.
- **Run** records approval and puts the tasks first in the queue. **Skip** leaves them listed on **Done** and on the **Setup** screen.
- Windows asks once for all of them (D3), here, on the **Install** page's approval card and on the **Setup** screen alike. The prompt names Windows PowerShell, which runs them, and the page says so; Phase 1 had two prompts, one from `reg.exe` and one from the DL Streamer installer.

How the single prompt works ([elevation.cjs](../../../Windows/ui/electron/services/elevation.cjs), [run_admin_tasks.ps1](../../../Windows/Scripts/run_admin_tasks.ps1)):

- The setup runner collects the administrator tasks due, in step order, and writes a plan to a new folder under `state/admin-tasks/`. The plan carries data only: the task ids, the DL Streamer version and the proxy. The helper accepts known task ids, a dotted version and an `http(s)://` proxy, so a changed plan cannot make it run anything else.
- The app runs the helper unelevated with `-Launch -RunAs`. It starts itself again with the `runas` verb, which is the prompt, and waits, so its exit code tells a declined prompt (1223) from a failure. The launcher is the shipped script rather than a generated `-EncodedCommand`, which security software tends to flag. A standard user approves with an administrator's credentials; the helper then runs as that account and still reaches the folder, through the Administrators group.
- An elevated process cannot pipe its output back to an unelevated app, so the helper writes a log next to the plan, with `@@admin` event lines, and a result file. The app follows the log: each row shows as running when its task starts and is checked again as soon as it ends, so long paths reads as fixed while DL Streamer is still installing. The folder is deleted afterwards, because the plan can hold proxy credentials.
- Long paths are set in the registry by the helper itself. DL Streamer runs the existing [check_dlstreamer.ps1](../../../Windows/Scripts/check_dlstreamer.ps1) `-Install`, which downloads the installer into a new folder under `%windir%\Temp` that only administrators and SYSTEM can write, so nothing can swap the installer between download and run. The elevated process gets a fresh environment, so the proxy comes from the plan.
- An unelevated app cannot stop an elevated process. **Cancel** leaves a `stop` file in the folder, which skips the tasks not yet started; the one under way finishes, and the run stops after it.

### 7.6 Install

```text
┌ Smart Classroom setup ─────────────────────────────────────────────┐
│ ✓ Welcome    Installing                              Step 3 of 7   │
│ ✓ Network    ✓ Administrator tasks (long paths, DL Streamer)  2:10 │
│ ✓ Features   ✓ Python 3.12                                    0:42 │
│ ✓ Admin      ● Python environment                            12:05 │
│ ● Install      Downloading openvino-2026.2.1-cp312-...  (98 MB)    │
│ ○ Done       ○ Grading conversion environment                      │
│              ○ Layout detection model                              │
│              ○ First start: download AI models                     │
│                                                                    │
│ You can leave this running. Your PC stays awake until it finishes. │
│ [Show details]                                        [Cancel]     │
└────────────────────────────────────────────────────────────────────┘
```

- **Queue.** It comes from a new `SetupRunner.plan()`, which `runAutomatic()` uses too, so the page lists exactly what will run. The last item is the backend's first start. It names the model being downloaded from the backend's download progress (Section 8.4), or, where none is reported, from the `Downloading {repo}@{revision} from ...` line that `download_snapshot()` in [model_download_helper.py](../../../Windows/utils/model_download_helper.py) logs for every model download.
- **Progress.** A step counter, the elapsed time per step and the current output line, with the full log under **Show details**. While a step or the backend's first start downloads a model, a progress bar takes the output line's place: the bytes so far of the total, the speed and the time left (Section 8.4). Other work shows no percentages, for lack of data to base them on.
- **Running unattended.** The PC is kept awake with `powerSaveBlocker` (`prevent-app-suspension`). Progress shows on the taskbar icon (`setProgressBar()`), and a Windows notification announces the end or a failure.
- **Interruptions.** Closing the window asks for confirmation; it stops the current step, and the next launch resumes on **Install** without asking again. **Cancel** stops the queue and offers **Resume**.
- **Failures.** The failed step expands with its classified cause (network, certificate, disk full, files in use, other) and these actions: **Retry**, **Back to Network** for network causes, **Copy diagnostics** and **Open Setup**.

### 7.7 Done

- What was installed, and what was skipped or failed, with the features each one affects.
- **Open Smart Classroom** goes to **Home** once the backend is healthy.
- **A failed first start.** The models download during the backend's first start, so that is where a network problem shows. **Done** reads the backend's log for the error it ended on, and classifies it as **Install** does, but only into the causes a download runs into: the network, a certificate, a model hub turning the network away for a while (ModelScope's rate limit, HTTP 429) and a full disk. It shows the cause and the error, and offers **Retry**, which starts the backend again, and **Show details**, the backend's log. For a network, certificate or rate-limit cause it also offers **Network settings**, which opens **Network**, where **Save and retry** saves the settings and starts the backend again. Any other failure shows its error and the log.
- Writes the completed record.

## 8. Architecture

### 8.1 Main Process

| Module | Change |
| --- | --- |
| `main.cjs` | The wizard branch in `prepareAndStartBackend()`. Keep-awake, taskbar progress, notification, and the close confirmation during installation. |
| `first-run.cjs` (new) | Reads and writes the record. A pure `needsWizard()` implementing Section 5, and the flow of Section 6 as a pure state machine (`next(state, event)`) that owns the countdown. |
| `network-probe.cjs` (new) | `candidates()` and `parseSystemRule()` for detection, `probeHost()` and `probeCandidate()` for the test, `classify()`, `evaluate()` for whether the recommended settings work, and `recommendedChanges()` for what the recommended path writes. |
| `setup-runner.cjs` | `plan()` returns the ordered `{ stepId, actionId, kind }` entries, where `kind` is `auto`, `elevated` or `manual`. `runAutomatic({ includeElevated })` puts approved elevated tasks first. The DL Streamer step is enabled only while video analytics is effectively enabled (D2). Phase 2: an elevated action declares an `adminTask` instead of running itself, and `runAdmin()` runs every one due in one batch, behind one prompt (Section 7.5), from **Fix**, the first run, or a row's own button. |
| `elevation.cjs` (new, Phase 2) | `runAdminTasks()`: writes the plan, starts the helper elevated, follows its log and reads its result. |
| `download-progress.cjs` (new, Phase 2) | Reads the progress lines of model downloads (Section 8.4). `process-manager.cjs` and `setup-runner.cjs` keep the latest on the service and on the step. |
| `Scripts/run_admin_tasks.ps1` (new, Phase 2) | The helper. With `-Launch -RunAs` it starts itself elevated and waits; elevated, it runs the tasks of a plan. A dry run without `-RunAs` needs no elevation, for tests. |
| `registry.cjs` | Exports `effectivelyEnabled()` for the setup runner. |
| `paths.cjs` | `stateDir()`, and in Phase 2 `adminTasksScript()`. |
| `ipc.cjs`, `preload.cjs` | The channels below. |

New IPC channels follow the existing rules in [ipc.cjs](../../../Windows/ui/electron/services/ipc.cjs): the sender must be the app's own window, and the renderer passes ids and values, never commands or paths.

| Channel | Purpose |
| --- | --- |
| `firstRun:get`, `firstRun:changed` (event) | The flow state, including the detection and test results with credentials masked, and the record. |
| `firstRun:send` | A user choice: `customize`, `installNow` (with `includeElevated`), `approveElevated` or `manual`. **Continue anyway**, **Retry** and **Resume** are all `installNow`; skipping the administrator tasks is not approving them. |
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
- A failed first start: `assistantModel.test.ts` reads the error and the cause from backend logs that end the way real failures do: a proxy that refuses, an unknown host, a certificate, ModelScope's rate limit and a full disk.
- The single prompt, without raising one: `setup-runner-admin.test.cjs` replaces the helper with a stand-in to cover the batch, a declined prompt, Cancel and a running backend; `elevation.test.cjs` runs the real launcher and helper as a dry run, started without `runas`. Manual: approve and decline the prompt, as an administrator and as a standard user with an administrator's credentials, and behind a proxy.
- Manual, on clean virtual machines: a direct connection, an explicit proxy, a PAC proxy, a proxy requiring authentication, Hugging Face blocked, cancel and resume, closing during installation, declining an administrator prompt, an upgrade from the previous release (no wizard expected), `--setup-only` before the first launch, and an unattended launch that must end with a healthy backend.
- CI lives in the separate `edge-ai-suites-tests` repository. Its `unit-integration` workflow runs pytest only, so neither `test:electron` nor vitest runs in CI today. Adding both there is a follow-up.
- Download progress: `test_download_progress.py` (pytest) drives Hugging Face's own progress bar helpers, and its `xet_get()` against a stand-in Xet session; `download-progress.test.cjs` covers reading the lines, the log store's tap and both snapshots; `downloadProgress.test.ts` the sizes and the time left.
- Its end-to-end installer boot reuses a provisioned user-data folder, where the Python environment is OK, so the wizard never appears there (Section 5). Covering the unattended first launch (Section 6.1) needs a case with an empty user-data folder, for example by pointing `SMART_CLASSROOM_USERDATA` at a new folder. The full first run then has to fit the runner's 30-minute health timeout, which suits a nightly schedule rather than every run.

### 8.4 Model Download Progress

The app starts the backend and the setup scripts with `SC_PROGRESS_EVENTS=1`. With it, [download_progress.py](../../../Windows/utils/download_progress.py) reports every snapshot downloaded through `download_snapshot()`, `text_gen_prepare.py` or `ensure_layout_model.py` in lines like this one:

```text
@@download {"repo":"Qwen/Qwen3-8B","hub":"huggingface","state":"running","done":1234,"total":5678,"speed":901.2,"files":3,"fileTotal":12}
```

There is one line when a download starts, at most one every half second while it runs, and one when it ends, with the state `done` or `failed`. Without the variable nothing is printed and nothing is hooked into the hubs, so a terminal keeps their own progress bars.

- **Hugging Face.** `snapshot_download(tqdm_class=...)` makes two bars with the class: one over all files' bytes and one counting files. Files kept in Xet storage, which most large files are, need more: hf_xet counts a file's bytes only once the whole file is put together, so the bar would stand still through the largest files and jump at the end. Its progress reports also count the bytes received over the network, so while a download is reported, a wrapper around `huggingface_hub.utils._xet.get_xet_session()` adds the share received of each Xet file. If a later huggingface_hub works differently, downloads go on as before and only the bar loses that detail.
- **ModelScope.** `snapshot_download(progress_callbacks=[...])` makes one callback per file. A retry reports again the bytes already in the partial file, so each file's count stops at the file's size.
- **The numbers.** `done` and `total` are bytes, and `speed` is measured over the last five seconds. The total grows while files start, because a hub learns a file's size only when that file starts. `fileTotal` is null for ModelScope, which does not say how many files there are.
- **Main process.** [download-progress.cjs](../../../Windows/ui/electron/services/download-progress.cjs) checks every field of a line. The process manager takes the lines out of a service's output through the log store's tap, after a child's tagged lines are attributed to the child, and keeps the latest on the service's snapshot (`download`) until the service stops. The setup runner keeps it on the running step (`progress`). The lines reach neither the log view nor the log files.
- **Renderer.** `DownloadBar` in `components/ui` draws the bar with text such as "1.20 GB of 4.60 GB · 11.8 MB/s · about 5 min left", in the 1024-based units File Explorer uses. It appears on **Done** during the backend's first start, on **Install** and the Setup screen under the step running, and on the Services screen under each service that is downloading.

## 9. Failure Handling and Edge Cases

| Situation | Behavior |
| --- | --- |
| The network test fails for every host | The flow stops on **Network**, which shows each cause. Nothing installs until the user continues (Section 6.3). |
| Only Hugging Face is blocked | ModelScope is preselected. |
| HTTPS inspection on the network | The test checks certificates against a list close to Python's `certifi`, so it fails with a certificate error where the model downloads would. A tool that trusts the Windows certificate store can still succeed where the test failed; the failure stops the flow, and the user can continue anyway (Section 6.3). **Install** also recognizes certificate errors and explains them. |
| The PAC script returns different proxies per host | The proxy for `pypi.org` is saved, and the test shows any host it fails for. |
| Free disk space below 50 GB | The flow stops on **Welcome**, with the warning shown. Installing needs **Continue anyway**. |
| The administrator prompt is declined | Every task it covered fails with "Administrator approval was declined", and the rest of the queue still runs. They stay listed on **Done** and on the **Setup** screen, which says to try again and approve the prompt. |
| **Cancel** while an administrator task runs | The task finishes, because the app cannot stop an elevated process; the tasks not yet started are skipped, and the run stops after it (Section 7.5). |
| A model download fails during the backend's first start | **Done** names the likely cause and shows the error, with **Retry** and, for a network cause, **Network settings** (Section 7.7). Files already downloaded are kept, so a retry continues from there. |
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
| 2 | **A single administrator prompt (D3), done.** Of the two options, (a) was chosen: an elevated helper the app starts, which performs both tasks and writes a log the app follows (Section 7.5). It downloads the DL Streamer installer itself, into a folder only administrators can write, rather than before elevation into a folder the user can write, as first planned. Option (b), both tasks in the NSIS installer, was rejected: per-user installs, the default, run the installer unelevated, so its prompt would only move; a source checkout never runs the installer; and the installer runs before the feature choice that decides whether DL Streamer is needed (D2). **Byte-level download progress, done** (Section 8.4): `tqdm_class` for Hugging Face, with the Xet session's own reports for files in Xet storage, and `progress_callbacks` for ModelScope. **Model preparation as a setup step, set aside.** The plan was a backend entry point that downloads the models of the enabled features without starting the server, run by **Install** and by `--setup-only`, so that a first launch only loads models (rule 4.1). With the progress shown on **Done**, what it would still add is help when a download fails, machines prepared in advance with `--setup-only`, and retries that do not restart the backend. That did not outweigh changing every component that prepares models: text generation, speech recognition, OCR, video analytics and content search. Instead, **Done** explains a failed first start and offers **Retry** and **Network settings** (Section 7.7). Rule 4.1 stays unmet, and `--setup-only` still leaves the model downloads to the first launch. | M |
| 3 | A `uv`-based bootstrap: no winget or preinstalled Python, and faster package installs. | L |

## 12. Open Items

- Measure the download sizes and durations shown on **Welcome** and on each **Install** step on the reference machine.
- Confirm the host list in Section 7.3 with a traffic capture.
- In `edge-ai-suites-tests`: run `test:electron` and vitest in the `unit-integration` workflow, and add the unattended first-launch case (Section 8.3).

## 13. One Set of Parts

This section first also kept the wizard after the first run, as a **Setup assistant** in review mode (D8): Overview, This PC, Network, Features and Repair pages, reached from the menu. Section 14 replaced it (D11).

**One set of parts (D10).** The assistant and the Setup, Configuration and Services screens are built from the same parts, and keep only their own layout:

| Part | Where | Used by |
| --- | --- | --- |
| Page header, buttons, banners, status rows, log viewer, colours | [src/components/ui](../../../Windows/ui/src/components/ui), `ui.css` | Every screen and page |
| Setup steps as rows, grouped by section or not | `SetupStepList` | Setup's checks; Install, Administrator tasks |
| Settings fields, rule problems and their fixes, pending edits | `SettingsFields`, `ProblemBanners`, `useSettingsDraft` | Configuration; Network, Features |
| Feature groups, each a section with its features and settings (D9) | `FeaturePicker` | Configuration's Features group; Features |
| Proxy fields with **Test connection** | `ProxySettings` | Configuration's Proxy group; Network |
| What is not working, and what **Fix** covers | [problemList.ts](../../../Windows/ui/src/services/problemList.ts) | Setup |
| What a step's status means | [setupStatus.ts](../../../Windows/ui/src/services/setupStatus.ts) | All of the above, and the landing logic |

The schema drives what the assistant shows. Feature groups are defined once, as `FEATURE_GROUPS` in [config-schema.cjs](../../../Windows/ui/electron/services/config-schema.cjs); a field appears in the assistant when it has an `onboarding` place, a feature group's id or `network`, replacing the earlier `wizard` flag. Device fields have none (rule 3.6). Which steps need administrator approval comes from the setup data (`repairKind` on each step, `elevates` on each action) rather than from step ids.

## 14. After the First Run: What Is Not Working

The review mode of Section 13 repeated the **Setup** screen. Its Overview, This PC and Repair pages and the Setup screen each listed what was not installed, with four buttons that repaired three different sets of steps. After the first run there is now one place, the **Setup** screen, and it starts with what is not working (D11).

```text
┌ Setup ─────────────────────────────────────── [Re-check] [Fix] ┐
│ 2 things need fixing.                                          │
│                                                                │
│ ✕ Python environment                                           │
│   Not created; the backend cannot start until it exists        │
│ ! Speaker diarization                           [Show setting] │
│   Speaker diarization needs a Hugging Face token. …            │
│                                                                │
│ Show output   All checks (12)                                  │
└────────────────────────────────────────────────────────────────┘
```

- **Only problems.** One row for each setup step that needs work (missing, failed or outdated) and for each rule problem in the saved settings, in the words of the step's own detail or the rule's message. Warnings and passed checks stay under **All checks**. A row stays while it is checked again, so **Re-check** never shows "nothing needs fixing" for a moment.
- **One Fix.** It is the first launch's automatic run with the administrator tasks included, through `setup:runAutomatic`: every repair that needs nobody, and every one Windows asks an administrator to approve, which the rows mark "needs administrator". While it runs, the rows show what waits, what runs, with its elapsed time and last output line, and what is fixed, and **Fix** becomes **Cancel**. The repair the app starts by itself at launch shows the same way.
- **A row's own button** only where **Fix** cannot help: **Recreate** for an environment that can only be rebuilt, which asks before it deletes anything, and **Show setting** for a rule problem, which opens **Configuration** at the field.
- **Failures say why.** A row whose repair failed names the likely cause with the classification the **Install** page uses, and offers **Proxy settings** for network and certificate causes, or **Open Services** when the backend holds files the repair replaces.
- **When nothing needs fixing,** the screen says so in its middle, with a large check mark: "Everything is working" when the backend runs, otherwise "Everything is installed" with **Start backend** when it is stopped, or **Open Services** while it starts. **Show output** and **All checks** sit under it; opening either moves it to the top.
- **One column,** at most 960 pixels wide and centred, as **Configuration** is, so rows and their text do not stretch across a wide window.
- **Below,** closed until asked for: the setup output, then every check with its own actions and **Copy diagnostics**, as the expert view.

Around it:

- The menu shows how many setup steps need work, on its **Setup** entry and as a dot on the closed menu, so a problem shows from every screen.
- At launch, the app opens on **Setup** while anything needs work or a repair runs, and on **Services** otherwise.
- **Services** links to **Setup** when the backend cannot start without the environment.
- The wizard is first-run only, without **This PC** (Section 7.2). Its disk space warning, with **Continue anyway**, also shows on the page whose button installs.
- Settings stay on **Configuration**, which has the wizard's feature groups and proxy test.
