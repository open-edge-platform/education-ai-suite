# Get Started on Windows

Smart Classroom for Windows is distributed as a desktop application installer. The
app checks and installs the prerequisites, edits the configuration, and starts and
stops the backend services, all from one window.

> [!NOTE]
> To run Smart Classroom from a source checkout, script a deployment, or build the
> installer yourself, see [Build from Source on Windows](./build-from-source-windows.md).

## Step 1: Download the Installer

1. Check that your machine meets the [System Requirements](./system-requirements.md).
2. Open the [Releases page](https://github.com/open-edge-platform/education-ai-suite/releases)
   of the repository.
3. Under **Assets** of the release you want, download
   `SmartClassroom-<version>-setup.exe`.

<!-- SCREENSHOT: Release assets list with SmartClassroom-<version>-setup.exe highlighted -->

> [!NOTE]
> The app checks the Intel GPU and NPU drivers but does not install them. Install or
> update the [NPU driver](./system-requirements.md#software-and-hardware-requirements)
> from an administrator account before you start.

## Step 2: Install the App

Run `SmartClassroom-<version>-setup.exe` and follow the installer:

1. **Choose Installation Options**: install for **Anyone who uses this computer**
   (requires administrator approval) or **Only for me**.
2. **Choose Install Location**: keep the default folder or pick another one.
3. **Finish**: the installer adds a **Smart Classroom** shortcut to the desktop and the
   Start menu, and can launch the app right away.

<!-- SCREENSHOT: Installer, Choose Installation Options page -->
<!-- SCREENSHOT: Installer, Choose Install Location page -->

The installed program folder is not modified while the app runs. Settings, models,
the Python environment, sessions, and logs are stored per user; see
[Where Your Data Is Stored](#where-your-data-is-stored).

## Step 3: Complete the Setup Screen

Launch **Smart Classroom** from the desktop or the Start menu. While anything still
needs doing, the app opens on the **Get started** screen, which lists what is missing.
The menu button at the top left switches between screens.

<!-- SCREENSHOT: Get started screen on first launch -->

Follow the links on **Get started**, or open **Setup** directly, and work down the list:

| Section | Covers |
| :--- | :--- |
| **System and drivers** | Operating system, processor, memory, free disk space, Intel GPU and NPU drivers, Windows long paths |
| **Software and environment** | Python 3.12, Node.js (bundled with the app), FFmpeg, DL Streamer, the Python environment, and the grading conversion environment and layout detection model |

Each row shows what was found and what it blocks. Rows the app can fix have a button:

- **Install** for Python, FFmpeg, and Deep Learning Streamer (DL Streamer)
- **Create** for the Python environment and the grading conversion environment
- **Prepare** for the layout detection model
- **Enable** for Windows long paths (shows an administrator prompt)

**Fix _n_ items** at the top runs everything outstanding in order. Progress appears in
the **Output** pane below, and **Copy diagnostics** puts the whole list on the
clipboard for a bug report.

<!-- SCREENSHOT: Setup screen with the Fix n items button and the Output pane -->

> [!IMPORTANT]
> If you are behind a proxy, set `HTTP_PROXY` and `HTTPS_PROXY` on the **Get started**
> or **Configuration** screen before you run the Setup actions. The installs and model
> downloads use these values.

> [!NOTE]
> Creating the Python environment downloads several gigabytes, and preparing
  the layout detection model downloads and converts it. Both take a while on a first run.

The backend cannot start until the Python environment exists.

## Step 4: Review the Settings

**Get started** shows the settings most people change. The **Configuration** screen has
the full list from `config.yaml` and `.proxy-config`, grouped and searchable.
**Show file** opens the file the screen writes to. For what each setting does, see
[Configure the Application](../advanced-setup-guide.md#configure-the-application).

<!-- SCREENSHOT: Configuration screen -->

> [!NOTE]
> Speaker diarization (identifying who is speaking) is optional and requires a
  one-time Hugging Face access token. The **Get started** screen flags this when
  diarization is enabled without a token; set it under **Configuration**, or see
  [Speaker Diarization Setup](../advanced-setup-guide.md#f-speaker-diarization-setup-optional).

## Step 5: Start the Backend

The backend does not start on its own. Start it in either of these ways:

- Select **Start backend** on the **Get started** screen.
- Open **Services** and select **Start** on the backend row.

<!-- SCREENSHOT: Services screen with the backend running and live logs -->

The **Services** screen shows the backend and every service it starts, with their
status and live logs. Use **Stop** and **Restart** there as needed. The first start
downloads and prepares the AI models, so it takes longer than later starts.

When you save a configuration change while the backend is running, the app offers
**Restart backend** so the change takes effect.

## Step 6: Use the App

Once the backend is running, open **Home**, **Content Search**, or **Grading** from the
menu.

| Screen | What it does |
| :--- | :--- |
| **Home** | Audio transcription, summary, mind map, video analytics, and class reports |
| **Content Search** | Upload materials, search them, and ask questions about them |
| **Grading** | Grade exam papers against a rubric |
| **Get started** | Overview of what is ready, what is missing, and the settings most people change |
| **Setup** | Prerequisite checks plus the Python environment and model preparation |
| **Configuration** | Edit `config.yaml` and `.proxy-config` |
| **Services** | Start, stop, and restart the backend, and watch live logs for it and every child service |

For a walkthrough of each feature, see [Application Flow](../application-flow.md),
[Content Search Flow](../content-search-flow.md), and [Grading Flow](../grading-flow.md).

## Update to a New Version

1. Stop the backend on the **Services** screen and close the app.
2. Download and run the newer `SmartClassroom-<version>-setup.exe`.
3. Launch the app and open **Setup**. If the **Python environment** row shows
   **Outdated**, select **Upgrade** to match the new release's requirements.

Your settings, models, sessions, and content search data are kept across updates.

## Where Your Data Is Stored

Everything the app writes is under `%LOCALAPPDATA%\SmartClassroom\`:

| Path | Contents |
| :--- | :--- |
| `config.yaml`, `.proxy-config` | Your settings, edited through the **Configuration** screen |
| `smartclassroom\` | Python environment for the backend |
| `venv_convert\` | Grading conversion environment |
| `models\` | Downloaded and converted AI models |
| `storage\` | Session recordings, transcripts, summaries, and reports |
| `content_search\` | Uploaded materials and the content search vector database |
| `logs\` | Service logs (**Open folder** on the **Services** screen opens them) and configuration backups |
| `huggingface\`, `paddlex\`, `pip-cache\` | Download caches |

## Automated Deployment

The installer accepts the standard silent-install options:

```powershell
# Install silently for the current user
.\SmartClassroom-<version>-setup.exe /S /currentuser

# Install silently for all users (run from an administrator PowerShell)
.\SmartClassroom-<version>-setup.exe /S /allusers

# Install to a specific folder; /D= must be the last option
.\SmartClassroom-<version>-setup.exe /S /currentuser /D=C:\Apps\SmartClassroom
```

The first-run work on the **Setup** screen is interactive. For unattended preparation
of a machine, the repository also provides PowerShell scripts that run from a source
checkout; see [Build from Source on Windows](./build-from-source-windows.md).

## Service Ports Reference

The backend services listen on the local machine only:

| Service | Port | Health Check |
| :--- | :--- | :--- |
| Backend | 8000 | <http://localhost:8000/health> |
| Content Search | 9011 | <http://localhost:9011/api/v1/system/health> (200 only when ChromaDB, file ingest, and video preprocess are ready too; 503 while any is starting) |
| Layout Detection | 9902 | <http://localhost:9902/health> |
| Grading | 9012 | <http://localhost:9012/api/v1/health> |

> [!NOTE]
> Layout Detection and Grading services only start when `grading.enabled: true` in `config.yaml`.

## Troubleshooting and Uninstall

See [Troubleshooting](../advanced-setup-guide.md#troubleshooting),
[Known Issues](../advanced-setup-guide.md#known-issues), and
[Uninstall the Application](../advanced-setup-guide.md#uninstall-the-application).

## Learn More

- [System Requirements](./system-requirements.md): Hardware, software, supported models, and weight formats.
- [Advanced Setup Guide](../advanced-setup-guide.md): Configuration reference, troubleshooting, and uninstall.
- [Build from Source on Windows](./build-from-source-windows.md): Source checkout, setup scripts, and building the installer.
- [Application Flow](../application-flow.md): End-to-end application flow.
- [Content Search Flow](../content-search-flow.md): The flow of the content search functionality.
