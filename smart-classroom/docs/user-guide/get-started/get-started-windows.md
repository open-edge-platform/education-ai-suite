# Get Started on Windows

Smart Classroom for Windows is distributed as a desktop application installer. The
app checks and installs the prerequisites, edits the configuration, and starts and
stops the backend services, all from one window.

> [!NOTE]
> To build the installer yourself, see
> [Build the Installer from Source](./build-from-source-windows.md).

## Step 1: Download the Installer

1. Check that your machine meets the [System Requirements](./system-requirements.md).
2. Open the [Releases page](https://github.com/open-edge-platform/education-ai-suite/releases)
   of the repository.
3. Under **Assets** of the release you want, download
   `SmartClassroom-<version>-setup.exe`.

> [!NOTE]
> The app checks the Intel GPU and NPU drivers but does not install them. Install or
> update the [NPU driver](./system-requirements.md#software-and-hardware-requirements)
> from an administrator account before you start.

## Step 2: Install the App

Run `SmartClassroom-<version>-setup.exe` and follow the installer:

1. **Choose Installation Options**: install for **Anyone who uses this computer**
   (requires administrator approval) or **Only for me**.
2. **Choose Install Location**: shows where the app will be installed. The folder
   follows the option chosen on the previous page and cannot be changed:
   `%LOCALAPPDATA%\Programs\Smart Classroom` for **Only for me**, and
   `C:\Program Files\Smart Classroom` for **Anyone who uses this computer**.
3. **Finish**: the installer adds a **Smart Classroom** shortcut to the desktop and the
   Start menu, and can launch the app right away.

![Installer: Choose Installation Options](../_assets/windows-installer-install-mode.png)<!--hide_directive{w=400px}hide_directive-->

![Installer: Choose Install Location](../_assets/windows-installer-install-location.png)<!--hide_directive{w=400px}hide_directive-->

The installed program folder is not modified while the app runs. Settings, models,
the Python environment, sessions, and logs are stored separately for each Windows
user, also when the app is installed for everyone; see
[Where Your Data Is Stored](#where-your-data-is-stored).

## Step 3: Run the Setup Assistant

Launch **Smart Classroom** from the desktop or the Start menu. On the first launch the
app opens the **setup assistant**. It installs everything Smart Classroom needs: Python
3.12 and FFmpeg when they are missing, the Python environment, and the prerequisites of
the features you choose. It then starts the backend, which downloads the AI models.
This downloads several gigabytes and takes a while; you can leave it running.

The steps on the left show where you are: **Welcome**, **Network**, **Features**,
**Administrator tasks** (only when needed), **Install**, and **Done**. The language
selector at the top switches between English and Chinese.

### Welcome: Install with the Recommended Settings

**Welcome** checks this PC and tests the network as soon as it opens:

- **This PC**: the operating system, processor, memory, free disk space, and drivers.
  Warnings do not stop the installation.
- **Network**: how the downloads connect. The assistant finds the proxy from the app's
  saved settings, the `HTTP_PROXY` and `HTTPS_PROXY` environment variables, or the
  Windows proxy settings, and tests that the download hosts answer through it.
- **AI models**: where the models come from. When Hugging Face cannot be reached and
  ModelScope can, the assistant chooses ModelScope.

When the checks pass, a countdown starts: "Installing with recommended settings in
15 s". When it ends, the installation starts with the recommended settings, so a first
launch needs no input. Select **Install now** to start at once, or **Customize** to
stop the countdown and choose the settings yourself.

![Setup assistant: Welcome](../_assets/windows-app-wizard-welcome.png)<!--hide_directive{w=700px}hide_directive-->

The countdown does not start in two cases, and the assistant waits for you instead:

- **The network test fails.** **Network** opens and shows what each download host
  answered: "Setup could not reach the download hosts, so it has not started
  installing." Enter or correct the proxy, select **Test connection**, then select
  **Next**.
- **Less than 50 GB of disk space is free.** **Welcome** shows a warning, because
  running out of space part-way is hard to recover from. Free some space, or select
  **Continue anyway** to install regardless.

### Customize: Network, Features, and Administrator Tasks

**Customize** takes you through the settings before anything large is downloaded.

**Network** shows the proxy the assistant found, and the model hub. Behind a proxy,
enter it as `http://host:port`, or `http://user:password@host:port` when the proxy asks
for a password. **Test connection** shows what each download host answers. Leave both
proxies empty for a direct connection. **Next** saves the settings.

![Setup assistant: Network](../_assets/windows-app-wizard-network.png)<!--hide_directive{w=700px}hide_directive-->

**Features** lists the features by what you use them for: **Classroom recording**,
**Video analytics**, **Content search**, and **Grading**. Setup only downloads what the
features you keep need. Each group's checkbox turns all of its features on or off, and
its features and settings are listed below it, such as the speech recognition model
and speaker diarization. Everything is on by default except **Grading**.

![Setup assistant: Features](../_assets/windows-app-wizard-features.png)<!--hide_directive{w=700px}hide_directive-->

**Administrator tasks** appears only when this PC needs one of them:

- **Windows long paths**, which lets downloads with deep folder paths succeed.
- **DL Streamer**, which runs the video analytics pipelines. It is needed only while
  video analytics is on.

Windows asks an administrator to approve them, once for all of them; the prompt names
Windows PowerShell. Choose to install them first, while you are at the screen, or to
skip them for now and install them later on the **Setup** screen. Then select
**Install**.

### Install

**Install** lists every step it will run, with the time each one takes and the line it
printed last. While a model downloads, a progress bar shows the amount downloaded, the
speed, and the time left. **Show details** shows the full output.

![Setup assistant: Install](../_assets/windows-app-wizard-install.png)<!--hide_directive{w=700px}hide_directive-->

- Your PC stays awake until the installation finishes. The taskbar icon shows the
  progress, and a Windows notification tells you when it ends.
- On the recommended path, administrator tasks do not hold up the installation. A card
  offers to install them; select **Install now** and approve the prompt, or leave them
  for later.
- **Cancel** stops the installation. What finished stays installed, and **Resume**
  continues with the rest. If you close the window, the app asks first, and the next
  launch resumes the installation.
- If a step fails, **Install** names the likely cause, such as the network, a
  certificate, or a full disk, and offers **Retry**. For a network cause it also offers
  **Network settings**. **Copy diagnostics** copies the details for a bug report.

### Done

**Done** lists what was installed and anything still to do, such as a skipped
administrator task. The backend then starts for the first time and downloads the AI
models, with a progress bar for each download. This first start takes a while; later
starts are faster. When the backend is ready, select **Open Smart Classroom**.

![Setup assistant: Done, during the first start](../_assets/windows-app-wizard-done.png)<!--hide_directive{w=700px}hide_directive-->

If the first start fails, **Done** shows the error and its likely cause, with **Retry**.
For a network or model hub problem it also offers **Network settings**, where **Save and
retry** saves the settings and starts the backend again. Files already downloaded are
kept, so a retry continues from where it stopped.

> [!NOTE]
> The setup assistant appears once for each Windows user. To install everything
> yourself instead, select **Set up manually** on **Welcome**: the app opens the
> **Setup** screen and installs nothing by itself.

## Step 4: Fix Problems on the Setup Screen

After the first run, the app prepares itself at every launch. It starts the backend
when the Python environment is fine. When something is missing, it repairs what needs no
administrator approval, then starts the backend. The app opens on **Setup** while
anything needs fixing, and the ☰ menu shows how many items need work.

**Setup** lists only what is not working, each with what was found:

- **Fix _n_ items** fixes everything the app can fix, in order. Items marked **needs
  administrator** show one Windows prompt for all of them, which names Windows
  PowerShell.
- A failed item names the likely cause. For a network cause it offers **Proxy
  settings**; when the backend is using files that the fix replaces, it offers **Open
  Services** to stop it first.
- A settings problem, such as diarization turned on without a Hugging Face token,
  offers **Show setting**, which opens **Configuration** at that setting.
- When nothing needs fixing, **Setup** says "Everything is working", or "Everything is
  installed" with **Start backend** when the backend is stopped.

![Setup screen with an item to fix](../_assets/windows-app-setup.png)<!--hide_directive{w=700px}hide_directive-->

![Setup screen when everything is working](../_assets/windows-app-setup-ready.png)<!--hide_directive{w=700px}hide_directive-->

**Show output** shows what the last fix printed. **All checks** lists every check, with
its own buttons, such as **Recreate** for the Python environment, which deletes it and
creates it again:

| Section | Covers |
| :--- | :--- |
| **System and drivers** | Operating system, processor, memory, free disk space, Intel GPU and NPU drivers, Windows long paths |
| **Software and environment** | Python 3.12, Node.js (bundled with the app), FFmpeg, DL Streamer, the Python environment, and the grading conversion environment and layout detection model |

**Copy diagnostics**, under **All checks**, puts the whole list on the clipboard for a
bug report.

## Step 5: Review the Settings

The **Configuration** screen has the full list of settings from `config.yaml` and
`.proxy-config`, grouped and searchable. Its **Features** and **Proxy** groups are the
same as the setup assistant's pages, including **Test connection**. **Show file** opens
the file the screen writes to. For what each setting does, see
[Configure the Application](../advanced-setup-guide.md#configure-the-application).

![Configuration screen](../_assets/windows-app-configuration.png)<!--hide_directive{w=700px}hide_directive-->

> [!NOTE]
> Speaker diarization (identifying who is speaking) is optional and requires a
  one-time Hugging Face access token. **Setup** flags this when diarization is enabled
  without a token; set it under **Configuration**, or see
  [Speaker Diarization Setup](../advanced-setup-guide.md#f-speaker-diarization-setup-optional).

## Step 6: Check the Backend

The app starts the backend at every launch once the Python environment exists. If you
stopped it, or it failed to start, start it in either of these ways:

- Select **Start backend** on the **Setup** screen.
- Open **Services** and select **Start** on the backend row.

![Services screen with live logs](../_assets/windows-app-services.png)<!--hide_directive{w=700px}hide_directive-->

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

For a walkthrough of each feature, see [Application Flow](../application-flow.md),
[Content Search Flow](../content-search-flow.md), and [Grading Flow](../grading-flow.md).

## Update to a New Version

1. Stop the backend on the **Services** screen and close the app.
2. Download and run the newer `SmartClassroom-<version>-setup.exe`. It installs over
   the existing version in the same folder; you do not need to uninstall first.
3. Launch the app. The setup assistant does not appear for an update. If the new
   release needs different Python packages, **Setup** lists the **Python environment**
   as outdated. Stop the backend on the **Services** screen, then select **Fix 1 item**
   on **Setup** to upgrade it.

Models, the Python environments, sessions, and content search data are kept across
updates. Your settings are kept too, unless the new version ships different default
settings:

- On the first start after such an update, `config.yaml` and the grading
  configuration are reset to the new defaults, and a message tells you so.
- The previous files are saved in `logs\config-backups` as `pre-update.*.bak`.
  Re-enter the settings you had changed, including the Hugging Face token, on the
  **Configuration** screen.
- Proxy settings (`.proxy-config`) are not reset.

## Where Your Data Is Stored

Everything the app writes is under `%LOCALAPPDATA%\SmartClassroom\` of the Windows user
running it:

| Path | Contents |
| :--- | :--- |
| `config.yaml`, `.proxy-config` | Your settings, edited through the **Configuration** screen |
| `smartclassroom\` | Python environment for the backend |
| `venv_convert\` | Grading conversion environment |
| `models\` | Downloaded and converted AI models |
| `storage\` | Session recordings, transcripts, summaries, and reports, and the GStreamer plugin cache |
| `chunks\` | Audio being transcribed, removed when the backend stops |
| `components\va\bin\mediamtx\` | The MediaMTX streaming server for video analytics, downloaded on first use |
| `content_search\` | Uploaded materials and the content search vector database |
| `grading\` | Grading configuration, uploaded rubrics, and grading results |
| `logs\` | Service logs (**Open folder** on the **Services** screen opens them) and configuration backups, including the `pre-update.*.bak` files saved by updates |
| `state\` | Records which shipped default settings your configuration came from |
| `huggingface\`, `paddlex\`, `pip-cache\` | Download caches |

## Automated Deployment

The installer accepts the standard silent-install options:

```powershell
# Install silently for the current user
.\SmartClassroom-<version>-setup.exe /S /currentuser

# Install silently for all users (run from an administrator PowerShell)
.\SmartClassroom-<version>-setup.exe /S /allusers
```

To prepare the machine without opening a window, run the app with `--setup-only`. It
installs what the setup assistant would install with the recommended settings, except
the administrator tasks, then exits:

```powershell
# Use "C:\Program Files\Smart Classroom" for an install for all users
$app = "$env:LOCALAPPDATA\Programs\Smart Classroom\Smart Classroom.exe"
(Start-Process $app -ArgumentList --setup-only -Wait -PassThru).ExitCode
```

| Exit code | Meaning |
| :--- | :--- |
| `0` | Everything is ready. |
| `1` | A step failed, or the backend still cannot start. |
| `2` | The backend can start, but items remain that need an administrator prompt or a confirmation on the **Setup** screen, such as Windows long paths or DL Streamer. |

`--setup-only` prints nothing to the console, because the app is not a console program.
Its output is in the `setup-*.log` files under `%LOCALAPPDATA%\SmartClassroom\logs\manager`.
It uses the proxy saved by the app or set in the `HTTP_PROXY` and `HTTPS_PROXY`
environment variables. The AI models are downloaded when the backend first starts.
After a successful run, the app does not show the setup assistant.

## Troubleshooting and Uninstall

See [Troubleshooting](../advanced-setup-guide.md#troubleshooting),
[Known Issues](../advanced-setup-guide.md#known-issues), and
[Uninstall the Application](../advanced-setup-guide.md#uninstall-the-application).

## Learn More

- [System Requirements](./system-requirements.md): Hardware, software, supported models, and weight formats.
- [Advanced Setup Guide](../advanced-setup-guide.md): Configuration reference, troubleshooting, and uninstall.
- [Build the Installer from Source](./build-from-source-windows.md): Build `SmartClassroom-<version>-setup.exe` yourself.
- [Application Flow](../application-flow.md): End-to-end application flow.
- [Content Search Flow](../content-search-flow.md): The flow of the content search functionality.
