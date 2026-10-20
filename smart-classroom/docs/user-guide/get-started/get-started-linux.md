# Get Started on Linux

This guide walks you through cloning the repository, configuring defaults, and running the application on Linux using the `setup.sh` script.

## Step 1: Prerequisites

Make sure the following are installed. See [System Requirements](./system-requirements.md) for details.

- Docker Engine and the Docker Compose plugin (your user must be able to run `docker` without `sudo`)
- Git
- Python 3 (`python3`) with `pyyaml` available (used by `setup.sh` helper scripts)
- Intel GPU drivers (optional, for GPU acceleration). When `/dev/dri` is present, `setup.sh` automatically enables the GPU compose overlay and sets `RENDER_GID` in `.env`.

> [!NOTE]
> Node.js for the UI build is provisioned by `setup.sh` through `scripts/node-setup.sh`.

## Step 2: Clone Repository

Go to the target directory of your choice and clone the suite.
If you want to clone a specific release branch, replace `main` with the desired tag.
To learn more about partial cloning, see the [Repository Cloning guide](https://docs.openedgeplatform.intel.com/dev/OEP-articles/contribution-guide.html#repository-cloning-partial-cloning).

```bash
git clone --filter=blob:none --branch main https://github.com/open-edge-platform/education-ai-suite.git
cd education-ai-suite/smart-classroom/Linux
```

## Step 3: Configuration

### A. Enable Feature Configuration

Features are enabled or disabled through the `features:` block in `config.yaml`. Only enabled features are initialized at startup. `setup.sh` derives `COMPOSE_PROFILES` in `.env` from this block.

```yaml
features:
  asr:                { enabled: true }   # Speech-to-text transcription
  summary:            { enabled: true }   # AI class summary / report
  mindmap:            { enabled: true }   # Mind map generation
  topic_segmentation: { enabled: true }
  video_analytics:    { enabled: true }   # Video ingestion / analytics
  board_ocr:          { enabled: true }   # OCR of the teacher's display (IFPD)
  content_search:     { enabled: true }   # Multimodal search + RAG service
  qa:                 { enabled: true }   # RAG-based Q&A over uploaded materials
```

### B. Default Configuration

Models are set in `config.yaml`. Changing `models.text_gen.vlm_name`, the embedding model, or the content search reranker is picked up by `setup.sh`, which syncs `components/vlm/config/startup-models.yaml` and `startup-models.gpu.yaml`.

```yaml
asr:
  provider: openai            # Supported: openvino, openai, funasr
  name: whisper-small
  device: CPU

text_gen:
  provider: vlm
  vlm_name: Qwen/Qwen3-VL-8B-Instruct
  device: GPU                 # Options: GPU or CPU
  weight_format: int4         # Supported: fp16, int4, int8
  max_new_tokens: 5120
```

### C. Hugging Face Token (Optional)

Speaker diarization (pyannote) and gated models need a Hugging Face token. Request access to the [Pyannote Speaker Diarization Community v1](https://huggingface.co/pyannote/speaker-diarization-community-1) model, create a Read token at [Hugging Face Access Tokens](https://huggingface.co/settings/tokens), then:

1. Set `diarization: true` under `models.asr` in `config.yaml`.
2. Add the token to `.env`:

```bash
HF_TOKEN=hf_your_access_token_here
```

> [!NOTE]
> `setup.sh` creates `.env` from `.env.example` on first run. If you want to set `HF_TOKEN` beforehand, run `cp .env.example .env` first. `setup.sh` warns when diarization is enabled and `HF_TOKEN` is missing.

## Step 4: Run the Setup Script

From the `Linux` directory, run:

```bash
chmod +x setup.sh
./setup.sh
```

The script performs the following:

1. Initializes the `edge-ai-libraries` (sparse checkout) and `performance-tools` git submodules.
2. Installs and verifies the Node.js toolchain for the UI.
3. Creates `.env` from `.env.example` if it does not exist.
4. Warns if diarization is enabled without `HF_TOKEN`.
5. Syncs `startup-models.yaml` and `startup-models.gpu.yaml` with `config.yaml`.
6. Derives `COMPOSE_PROFILES` from the enabled features.
7. Detects an Intel GPU (`/dev/dri`) and enables `docker/docker-compose.gpu.yml` with `RENDER_GID`.
8. Validates the compose config, then builds and starts the stack (`docker compose up -d --build`).
9. Waits for the `smart-classroom-app` container to become healthy.
10. Runs `npm install` and starts the UI dev server in the background.

> [!NOTE]
> First-time execution can take a long time (up to about 30 minutes) while models are downloaded and exported. Override the wait time with `HEALTH_TIMEOUT_S`, for example `HEALTH_TIMEOUT_S=3600 ./setup.sh`.

On success you should see:

```text
[setup] ✅ App is healthy: http://localhost:8000/
[setup] ✅ UI: http://localhost:5173/  (logs: .../ui/vite-dev.log)
[setup] ✅ setup complete.
```

## Step 5: Verify and Manage the Application

- Backend: <http://localhost:8000/>
- UI: <http://localhost:5173/> (change with `UI_PORT=<port> ./setup.sh`)

Check status and logs:

```bash
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f app
docker compose -f docker/docker-compose.yml logs -f model-downloader ovms
```

Stop the services:

```bash
docker compose -f docker/docker-compose.yml down
kill $(cat ui/vite-dev.pid)   # stop the UI dev server
```

> [!IMPORTANT]
> After changing `config.yaml`, rerun `./setup.sh` so that profiles and model lists are regenerated and the stack restarts with the new configuration.

## Network Requirements

- **Proxy**: If behind a proxy, configure `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` for the shell and for Docker.
- **Model Downloads**: Stable access to `huggingface.co` is required to download pre-trained models.
