# 🎓 Smart Classroom
The Smart Classroom project is a modular, extensible framework designed to process and summarize educational content using advanced AI models. It supports transcription, summarization, and future capabilities like video understanding and real-time analysis. 

## This project provides: 

### 🔊 Audio file processing and transcription (e.g., Whisper, Paraformer) 
### 🧠 Summarization using powerful LLMs (e.g., Qwen, LLaMA) 
### 📦 Plug-and-play architecture for integrating new ASR and LLM models 
### ⚙️ API-first design ready for frontend integration 
### 🛠️ Ready-to-extend for real-time streaming, diarization, translation, and video analysis 
The goal is to transform raw classroom recordings into concise, structured summaries for students, educators, and learning platforms.

---

### ✅ 1. **Install Dependencies**

**a. Install [FFmpeg](https://ffmpeg.org/download.html)** (required for audio processing):

* On **Windows**:
  Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html), and add the `ffmpeg/bin` folder to your system `PATH`.

**b. Install Python dependencies:**

```bash
pip install -r requirements.txt
```

---

### ✅ 2. **Run the Application**

```bash
python main.py
```

You should see logs similar to this:

```
pipeline initialized
[INFO] __main__: App started, Starting Server...
INFO:     Started server process [21616]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

This means your pipeline server has started successfully and is ready to accept requests.

---