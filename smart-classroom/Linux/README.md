# Smart Classroom

The **Smart Classroom** project is a modular, extensible framework designed to process and summarize educational content using advanced AI models for the Linux OS. It supports transcription, summarization, mindmap generation, future capabilities like video understanding, multimodal content search, and real-time video analytics.

## Main Features

The main features are as follows:

### Audio Pipeline

- Audio transcription with ASR models (e.g., Whisper, Paraformer)
- Speaker diarization using Pyannote Audio models (optional)
- Summarization using powerful LLMs (e.g., Qwen, LLaMA)
- MindMap generation using Mermaid.js for visual diagram rendering of the summary
- Content segmentation for automatic topic extraction from transcripts

### Video Analytics Pipeline

- Real-time video analysis across three concurrent camera streams (front, back, content)
- Person detection and pose estimation using YOLO models with keypoint skeleton tracking
- Person re-identification for tracking individual students across frames
- Classroom statistics including student count, stand-up events, and hand-raise events

### Content Search

- Multimodal semantic search across videos, images, and documents
- AI-driven video summarization using Vision Language Models (VLM)
- Document text extraction with OCR support (PaddleOCR)
- RAG-based Question & Answer over uploaded educational materials
- Vector-based retrieval using ChromaDB with CLIP and mE5 embeddings

## Architecture

- Plug-and-play architecture for integrating new ASR, LLM, and video analytics models
- API-first design ready for frontend integration.

## Get Started

To see the system requirements and other installations, see the following guides:

- [System Requirements](./docs/user-guide/get-started/system-requirements.md): Check the hardware and software requirements for deploying the application.
- [Get Started](./docs/user-guide/get-started.md): Follow step-by-step instructions to set up the application.
