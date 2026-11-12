# Build from Source on Windows

Most users install Smart Classroom with the desktop app installer; see
[Get Started on Windows](./get-started-windows.md). This guide is for developers and
for automated deployments that run Smart Classroom from a source checkout. It covers
the setup scripts, the manual setup, and building the installer.

> [!IMPORTANT]
> Use **Windows PowerShell** (not Command Prompt/CMD) for all steps in this guide.
> PowerShell scripts (`.ps1` files) will not execute in CMD — they will only open as text files.

## Clone the Repository

Go to the target directory of your choice and clone the suite.
If you want to clone a specific release branch, replace `main` with the desired tag.
To learn more about partial cloning, see the [Repository Cloning guide](https://docs.openedgeplatform.intel.com/dev/OEP-articles/contribution-guide.html#repository-cloning-partial-cloning).

```bash
git clone --filter=blob:none --sparse --branch main https://github.com/open-edge-platform/education-ai-suite.git
cd education-ai-suite
git sparse-checkout set smart-classroom/Windows
cd smart-classroom/Windows
```

In a source checkout, the settings live in `smart-classroom/Windows/config.yaml`, and
models, logs, and session data are written under `smart-classroom/Windows`. For what
each setting does, see
[Configure the Application](../advanced-setup-guide.md#configure-the-application).

From here, pick one of three ways to run it:

| | [Desktop app from source](#option-1-desktop-app-from-source) | [Setup scripts and browser UI](#option-2-setup-scripts-and-the-browser-ui) | [Manual setup](#option-3-manual-setup) |
| :--- | :--- | :--- | :--- |
| Commands to run | `.\start-desktop-app.ps1` | `.\setup-smart-classroom.ps1`, then `.\start-smart-classroom.ps1` | One step at a time |
| Prerequisites and installs | **Setup** screen | One scripted pass through everything | By hand |
| Unattended use | No | Yes, with `-Silent` | No |
| Where the UI runs | Its own desktop window | Browser at <http://localhost:5173> | Browser at <http://localhost:5173> |

---

## Option 1: Desktop App from Source

```powershell
.\start-desktop-app.ps1
```

The script asks for your proxy settings, installs Node.js through winget if it is
missing, builds the UI, and starts the same desktop app the installer ships. It then
starts the backend automatically once the Python environment exists. The screens are
described in [Get Started on Windows](./get-started-windows.md#step-3-complete-the-setup-screen).

**Optional parameters:**

- `-Dev` — Run the Vite dev server with hot reload
- `-NoAutoStart` — Open the app without starting the backend automatically
- `-SkipNodeInstall` — Fail instead of installing Node.js when it is missing
- `-Silent` — Skip the proxy prompts and use the saved `.proxy-config`

---

## Option 2: Setup Scripts and the Browser UI

Use this path for unattended installs or when you want the services in visible console
windows.

### Step 1: Run the Setup Script (First-Time Only)

```powershell
.\setup-smart-classroom.ps1
```

> [!NOTE]
> If all prerequisites are already installed (FFmpeg, DL Streamer, Python
  dependencies), you can skip setup and go straight to `.\start-smart-classroom.ps1`.

The setup script will:

1. **[1] Check System Requirements**
   - OS version, CPU, RAM, storage
   - Python and Node.js versions

2. **[2] Application Dependency Check**
   - FFmpeg (auto-install if missing)
   - DL Streamer: auto-download and run the installer [`dlstreamer-2026.1.0-win64.exe`](#b-install-dl-streamer)

3. **[3] Configure Settings**
   - [3.1] Feature Configuration (enable/disable individual application features)
   - [3.2] Language & ASR Configuration (provider, model, device)
   - [3.3] Upload Size Limits
   - [3.4] OCR Configuration
   - [3.5] Board OCR Configuration
   - [3.6] Grading Configuration (enable/disable Smart Grading)

> [!NOTE]
> Speaker diarization (identifying who is speaking) is optional and requires a one-time
  Hugging Face access token setup if enabled — see
  [Speaker Diarization Setup](../advanced-setup-guide.md#f-speaker-diarization-setup-optional).

### Step 2: Start the Services

Use the start script for subsequent runs, or after modifying `config.yaml`:

```powershell
.\start-smart-classroom.ps1
```

**Optional parameters:**

- `-Electron` - Shortcut for `.\start-desktop-app.ps1`; see [Option 1](#option-1-desktop-app-from-source)
- `-Silent` - Unattended mode for CI/Ansible (skips all prompts, auto-restarts services)
- `-NoElevate` - Never show a UAC prompt. The services always run as the current user; only enabling Windows long paths needs administrator privileges, and the script requests them for that change alone (never in `-Silent` mode)
- `-NoWindowsTerminal` - Use Invoke-WmiMethod instead of Windows Terminal (for remote sessions/Ansible)

```powershell
# Example: Automated deployment
.\start-smart-classroom.ps1 -Silent -NoElevate -NoWindowsTerminal
```

The startup script performs:

- **Service Detection** - Checks running services
- **Restart Options** - Restart, skip, or abort choices (auto in `-Silent` mode)
- **Proxy Configuration** - Loads from `.proxy-config`
- **Sequential Launch** - Backend -> Content Search -> Grading (if enabled) -> Frontend
- **Graceful Shutdown** - `Q` to stop all, `E` to keep running (auto-exits in `-Silent` mode)

### Step 3: Open the UI

Once all services are running, open your browser:

- <http://localhost:5173>

The UI is only reachable from this machine.

### Setup Scripts - Troubleshooting

If you encounter issues with the setup scripts, refer to the manual steps below:

| Issue | Solution |
| :--- | :--- |
| `PSSecurityException` when running `.ps1` scripts | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in PowerShell |
| FFmpeg installation fails | See [Install FFmpeg](#a-install-ffmpeg-required-for-audio-processing) |
| DL Streamer download fails | See [Install DL Streamer](#b-install-dl-streamer) |
| Python dependencies fail | See [Install Python Dependencies](#c-install-python-dependencies) |
| Content Search fails | See [Set Up Content Search](#step-3-set-up-content-search) |
| Frontend fails to start | See [Bring Up the Frontend](#step-5-bring-up-the-frontend) |

---

## Option 3: Manual Setup

### Step 1: Install Dependencies

#### A. Install FFmpeg (Required for Audio Processing)

Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html), and add the `ffmpeg/bin` folder to your system `PATH`.

#### B. Install DL Streamer

Download the Deep Learning Streamer (DL Streamer) installer from [DL Streamer assets on GitHub](https://github.com/open-edge-platform/dlstreamer/releases).
For details, refer to the [Install Guide](https://docs.openedgeplatform.intel.com/dev/edge-ai-libraries/dlstreamer/install/install_guide_windows.html).

> [!NOTE]
> DL Streamer 2026.2.0 is the latest verified version. Also update your [NPU driver](./system-requirements.md#software-and-hardware-requirements) to the latest version for compatibility.

Installing DL Streamer and the NPU driver needs administrator privileges. Start the application itself from a normal (non-administrator) shell.

#### C. Install Python Dependencies

It’s recommended to create a **dedicated Python virtual environment** for the base
dependencies. Run these commands from `smart-classroom`, the parent of the `Windows`
folder:

```bash
python -m venv smartclassroom
smartclassroom\Scripts\activate

# Use Python 3.12.x before running pip.
cd Windows
python.exe -m pip install --upgrade pip
pip install --upgrade -r requirements.txt
```

#### D. Install LibreOffice (Optional)

See [Install LibreOffice](../advanced-setup-guide.md#install-libreoffice-optional-feature-dependent).

### Step 2: Run the Backend

From `smart-classroom/Windows`, with the virtual environment activated, run:

```bash
python main.py
```

You should see backend logs similar to this:

```text
pipeline initialized
[INFO] __main__: App started, Starting Server...
INFO:     Started server process [21616]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

This means your pipeline server has started successfully and is ready to accept requests.

### Step 3: Set Up Content Search

Content Search provides multimodal semantic search, AI-driven video summarization, and RAG-based Q&A over uploaded educational materials.

Content Search runs in the same `smartclassroom` environment as the backend.

> [!NOTE]
> When the `content_search` feature is enabled in `config.yaml`, the backend (`main.py`) automatically launches the Content Search services on startup and shuts them down when it exits.

When all services are ready:

```text
[launcher] All 4 services are ready. (startup took XXs)
[launcher] You can use Ctrl+C to stop all services.
```

Verify the service status:

```PowerShell
Invoke-RestMethod -Uri "http://127.0.0.1:9011/api/v1/system/health"
```

This endpoint aggregates every service the launcher starts (ChromaDB, video
preprocess, file ingest, and the Content Search API itself). It answers `200`
with `status: "ok"` only when all of them are ready, and `503` with
`status: "degraded"` until then - the `services` map in the body names what is
still missing. `Invoke-RestMethod` throws on the `503`, so use
`try { ... } catch { $_.ErrorDetails.Message }` to read the detail while
services are still coming up.

> [!NOTE]
> First-time execution may take several minutes as AI models (CLIP, BGE, Qwen VLM) are downloaded.

- **Proxy**: If behind a proxy, ensure `HTTP_PROXY` and `HTTPS_PROXY` environment variables are configured.
- **Model Downloads**: Stable access to `huggingface.co` is required for downloading pre-trained models.
- **Windows Long Paths**: Move the project to a shallow directory (e.g., `C:\User\CS`) or enable long paths once from an administrator PowerShell:

  ```PowerShell
  New-ItemProperty -Path "HKLM:\System\CurrentControlSet\Control\FileSystem" `
  -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
  ```

### Step 4: Set Up Grading (Optional)

> [!NOTE]
> Skip this step if `grading.enabled: false` in `config.yaml`.

Smart Grading uses a layout detection model that requires a one-time conversion from Paddle format to OpenVINO™ IR. This step creates a dedicated conversion environment.

#### A. Create the Model Conversion Environment

```PowerShell
cd smart-classroom\Windows\components\grading\providers\layout_detection_service
python -m venv venv_convert
.\venv_convert\Scripts\pip install -r requirements_convert.txt
```

#### B. Convert and Download the Layout Detection Model

```PowerShell
.\venv_convert\Scripts\python ensure_layout_model.py
```

> [!NOTE]
> This downloads PP-DocLayoutV2 (~200 MB) and converts it to OpenVINO™ IR. Subsequent runs detect the existing model and skip this step automatically.

#### C. Launch Grading Services

Open two new terminal windows (the Backend terminal must remain running):

**Terminal — Layout Detection (port 9902):**

```PowerShell
cd smart-classroom\Windows\components\grading\providers
python .\layout_detection_service\layout_detection_server.py
```

**Terminal — Grading Service (port 9012):**

```PowerShell
cd smart-classroom\Windows\components\grading
python grading_service.py
```

### Step 5: Bring Up the Frontend

> [!NOTE]
> Open a new PowerShell window for the frontend.
> The backend and Content Search terminals stay busy serving requests.

```bash
cd <path-to>\education-ai-suite\smart-classroom\Windows\ui
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

> [!WARNING]
> Keep the frontend bound to `127.0.0.1`. The dev server proxies `/api/v1` and
  `/grading-api` to the Content Search and Grading backends, which have no
  authentication. Binding it to `0.0.0.0` exposes those backends, including
  their file read and write APIs, to every device on the network.

### Step 6: Access the UI

After starting the frontend, open the Smart Classroom UI in a browser:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

The UI is only reachable from the machine running the services. If you changed
the port, adjust the URL accordingly.

---

## Run and Package the Desktop App

The desktop app is the React UI wrapped in Electron. In a source checkout it can be
run against the services you started above, or packaged into the installer.

```bash
cd <path-to>\education-ai-suite\smart-classroom\Windows\ui
npm install

# Development: opens the desktop window and starts the dev server on 5173
npm run electron:dev

# Production preview: builds the UI and runs the packaged launch path, no dev server.
npm run electron:preview

# Package the Windows installer:
#   release\SmartClassroom-<version>-setup.exe
npm run electron:build
```

> [!NOTE]
> The Electron runtime binary is fetched lazily the **first time Electron runs**
  (`npm run electron:dev` / `electron:preview`). Behind a proxy, the first launch
  needs the proxy variables `ELECTRON_GET_USE_PROXY=true` and
  `GLOBAL_AGENT_HTTPS_PROXY=<proxy>` in addition to the usual
  `HTTP_PROXY` / `HTTPS_PROXY`. The `npm run electron:build` downloads
  its own copy via electron-builder and honors the standard `HTTPS_PROXY`.

For the desktop app's architecture and data locations, see the
[UI README](../../../Windows/ui/README.md).

---

## Source Checkout - Troubleshooting

- **Frontend not opening:**
  Ensure you ran `npm run dev` in a second terminal after starting `python main.py`.

- **Backend not ready:**
  Wait until Uvicorn shows **"Application startup complete"** and is listening on port **8000**.

- **Nothing at http://localhost:5173:**
  Check that the frontend terminal shows the Vite server running and no port conflict.

- **Auto reload not happening:**
  Refresh manually if the backend was restarted after initial UI load.

- **Manual video file path input in the browser:**
  In a web browser, you must manually specify the path to video files from your
  local system in the base directory input. The desktop app does not need this.

- If you see the following error while running the DL Streamer setup script:

  ```text
  .\setup_dls_env.ps1
    CategoryInfo          : SecurityError: (:) [], PSSecurityException
    FullyQualifiedErrorId : UnauthorizedAccess
  ```

  Run the command:

  ```bash
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
  ```

For model and runtime errors, see [Troubleshooting](../advanced-setup-guide.md#troubleshooting).
In a source checkout, the `models` folder it mentions is `smart-classroom/Windows/models`.

## Remove a Source Installation

1. **Delete the Python virtual environment folder:** \
   *education-ai-suite/smart-classroom/smartclassroom*. \
   For the grading model conversion environment (if created): *education-ai-suite/smart-classroom/Windows/components/grading/providers/layout_detection_service/venv_convert*.
2. **Remove the models directory:** *education-ai-suite/smart-classroom/Windows/models*.
3. **Remove the content search database:**
   Remove uploaded files, the vector database, and the upload record at *education-ai-suite/smart-classroom/Windows/content_search/data*.

## Service Ports Reference

| Service | Port | Health Check |
| :--- | :--- | :--- |
| Backend | 8000 | <http://localhost:8000/health> |
| Content Search | 9011 | <http://localhost:9011/api/v1/system/health> (200 only when ChromaDB, file ingest, and video preprocess are ready too; 503 while any is starting) |
| Layout Detection | 9902 | <http://localhost:9902/health> |
| Grading | 9012 | <http://localhost:9012/api/v1/health> |
| Frontend (browser UI) | 5173 | <http://localhost:5173> |

> [!NOTE]
> Layout Detection and Grading services only start when `grading.enabled: true` in `config.yaml`.
> The desktop app is its own frontend and does not use port 5173.

---

## Optional: Flutter + RAG Companion App

Separately from the Smart Classroom app above, the repository also ships a
standalone **Flutter + RAG** demo app — a lightweight Content Search Q&A UI,
independent of Smart Classroom's own frontend. It lives under `utils/flutter`
at the repository root (not under `smart-classroom/Windows`), is Windows-only
(PowerShell `setup.ps1`/`start.ps1`, no Linux equivalents), and the sparse
checkout in [Clone the Repository](#clone-the-repository) does not pull it in
by default.

Its **Agentic/Coding Companion mode** (`/sc-setup`, `/sc-up`, `/sc-doctor`,
`/sc-upload`, `/sc-qa`, `/sc-files`) is driven by skill `.md` files under
`.github/skills`, plus the agent-instructions files every coding assistant
starts from: `.github/copilot-instructions.md` (Copilot), `.cursor/rules/sc.mdc`
(Cursor — itself just a router back to `.github/skills`), and the root-level
`AGENTS.md`/`CLAUDE.md`. All of these are also outside `smart-classroom/Windows`,
so bring `.github` and `.cursor` along too if you want that mode, not just
`utils/flutter` on its own. `AGENTS.md`/`CLAUDE.md` need no extra step — cone-mode
sparse checkout always keeps root-level files regardless of which directories
you set.

To get them too, add their paths to an existing sparse checkout (run from the
`education-ai-suite` repository root):

```bash
git sparse-checkout add utils/flutter .github .cursor
```

Or, if cloning fresh, set all four paths at once:

```bash
git clone --filter=blob:none --sparse --branch main https://github.com/open-edge-platform/education-ai-suite.git
cd education-ai-suite
git sparse-checkout set smart-classroom/Windows utils/flutter .github .cursor
```

For setup, usage, and architecture, see:

- [`utils/flutter/README.md`](../../../../utils/flutter/README.md) — main guide:
  quick start, traditional UI mode, agentic/coding-companion mode,
  architecture, and troubleshooting.
- [`.github/skills/README.md`](../../../../.github/skills/README.md) — the skills
  catalog (`/sc-setup`, `/sc-up`, `/sc-doctor`, `/sc-upload`, `/sc-qa`, `/sc-files`)
  used by the app's Agentic/Coding Companion mode.

## Learn More

- [Get Started on Windows](./get-started-windows.md): Install the desktop app.
- [Advanced Setup Guide](../advanced-setup-guide.md): Configuration reference, troubleshooting, and uninstall.
- [System Requirements](./system-requirements.md): Hardware, software, supported models, and weight formats.
