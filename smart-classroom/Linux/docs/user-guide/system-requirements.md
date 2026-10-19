# System Requirements

This page provides detailed hardware, software, platform requirements, and supported models to help you set up and run the application efficiently.

## Software and Hardware Requirements

- **OS**: Ubuntu 24.04 LTS
- **Recommended processor**: Intel® Core Ultra Series 1, 2, and 3 Processors (with integrated GPU support)
- **Memory**: 32 GB RAM (minimum recommended)
- **Storage**: At least 50 GB free (for models, Docker images, and logs)
- **GPU/Accelerator**: Intel® iGPU (Core Ultra Series 1, Arc GPU, or higher) for summarization acceleration
- **NPU**: Intel® NPU (Core Ultra Series 1 or higher) for Video pipelines
- **GPU/NPU Drivers**: Install the latest Intel GPU and NPU drivers from [Intel NPU Driver releases](https://github.com/intel/linux-npu-driver/releases) and the [Intel GPU compute runtime](https://github.com/intel/compute-runtime/releases)
- **Docker**: Docker Engine and Docker Compose plugin
- **Python**: 3.12
- **Node.js**: v18+ (for frontend)

## Audio Pipeline Supported Models

### ASR (Automatic Speech Recognition)

- **Whisper (all models supported)**
  - Recommended: `whisper-small` or lower for CPU efficiency
  - Runs on **CPU** (Whisper is CPU-centric)
- **FunASR (Paraformer)**
  - Recommended for **Chinese transcription** (`paraformer-zh`)
- Supports transcription of .mp3/.wav audio files up to 45 minutes long.

### Summarization (LLMs)

- **Qwen Models (OpenVINO™)**
  - `Qwen3-VL-8B-Instruct` (default, shared vision-language model)
  - `Qwen3.5-9B`
- Summarization supports up to 5,120 tokens on GPU
- Run summarization on **GPU** (Intel® iGPU / Arc GPU) for faster performance.

### Content Segmentation and Topic Search

- **Embedding Model**: `intfloat/multilingual-e5-small` for semantic topic indexing and search
- **Vector Store**: ChromaDB
- **Content segmentation**: uses the shared vision-language model (`Qwen3-VL-8B-Instruct` by default)

### Supported Weight Formats

- **int4** → Recommended default (fast + memory-efficient on GPU)
- **int8** → Higher accuracy, larger memory footprint
- **fp16** → Full precision (use only if sufficient memory available)
