import argparse
import requests
import os
import json
import time
import sys
from pathlib import Path
from typing import Optional
from pydub import AudioSegment
import yaml

# Ensure the parent directory is in sys.path for direct script execution
if __name__ == "__main__" and __package__ is None:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from components.asr.funasr.paraformer import Paraformer
from components.asr.openai.whisper import Whisper
from components.llm.ipex.summarizer import Summarizer as IpexSummarizer
from components.llm.openvino.summarizer import Summarizer as OvSummarizer

from evaluation.template import templ_sum_en, templ_sum_zh, templ_score_en, templ_score_zh


JWT_token = "{your JWT token}"

def get_audio_length_pydub(wav_file: str) -> float:
    """Return the length of the audio file in seconds."""
    audio = AudioSegment.from_file(wav_file)
    return len(audio) / 1000.0  # Convert ms to seconds

def transcribe(model_name: str, local_audio_path: str) -> str:
    """Transcribe audio using ASR model."""
    if "paraformer" in model_name:
        model = Paraformer(model_name, device="cpu")
    elif "whisper" in model_name:
        model = Whisper(model_name, device="cpu")
    else:
        print("Unknown transcription model")
        return None
    return model.transcribe(local_audio_path)

def summarize(model_name: str, prompt, provider) -> str:
    """Generate a summary using the Summarizer model."""
    if provider == "openvino":
        model = OvSummarizer(model_name, "xpu")
    elif provider == "ipex":
        model = IpexSummarizer(model_name, "xpu")
    else:
        print("Unknown summarization model")
        return None
    result = ""
    for response in model.generate(prompt):
        result += response
    return result

def evaluate(eval_model: str, prompt: str, request_url: str) -> str:
    """Evaluate the summary using an external API."""
    payload = {
        "model": eval_model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {JWT_token}",
    }
    try:
        response = requests.post(request_url, json=payload, headers=headers, verify=False)
        response.raise_for_status()
        completion = response.json()
        result = completion['choices'][0]['message']['content']
        return result
    except Exception as e:
        print(f"Evaluation request failed: {e}")
        return ""

def main():
    parser = argparse.ArgumentParser(description="Evaluate transcript summary")
    parser.add_argument("--asr_model", help="ASR model")
    parser.add_argument("--audio_file", help="Audio file", required=True)
    parser.add_argument("--sum_model", help="Summarizer model")
    parser.add_argument("--sum_provider", help="Summarizer model provider, ov or ipex")
    parser.add_argument("--config", help="Path to config.yaml", default="config.yaml")
    parser.add_argument("--request_url", help="Request URL for API", default="https://deepseek.intel.com/api/chat/completions")
    parser.add_argument("--eval_model", help="Evaluation model", default="emr./models/DeepSeek-R1-Channel-INT8")
    parser.add_argument("--language", help="Language for the prompt, en or zh", default="en")
    parser.add_argument("--result_dir", help="Directory to save results")
    parser.add_argument("--sum_result_file", help="File to save summary result", default="summary.txt")
    parser.add_argument("--transcript_file", help="File to save transcript result", default="transcript.txt")
    parser.add_argument("--eval_report_file", help="File to save evaluation report", default="eval_report.txt")
    parser.add_argument("--skip_transcribe", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--skip_summarize", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--skip_evaluate", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    # Load config.yaml
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Get asr_model from args or config
    asr_model = args.asr_model
    if not asr_model:
        asr_model = config.get("models", {}).get("asr", {}).get("name")
        if not asr_model:
            print("asr_model must be specified via --asr_model or in config.yaml")
            sys.exit(1)

    # Get sum_model from args or config
    sum_model = args.sum_model
    if not sum_model:
        sum_model = config.get("models", {}).get("summarizer", {}).get("name")
        if not sum_model:
            print("sum_model must be specified via --sum_model or in config.yaml")
            sys.exit(1)

    # Get sum_provider from args or config
    sum_provider = args.sum_provider
    if not sum_provider:
        sum_provider = config.get("models", {}).get("summarizer", {}).get("provider", "")
        if not sum_provider:
            print("sum_provider must be specified via --sum_provider or in config.yaml (provider=openvino/ipex)")
            sys.exit(1)

    if sum_provider.lower() not in ["openvino", "ipex"]:
        print("sum_provider must be either openvino or ipex")
        exit(0)

    language = args.language
    if not language:
        language = config.get("models", {}).get("asr", {}).get("language")
        if not language:
            print("language must be specified via --language or in config.yaml")
            sys.exit(1)

    if language == "en":
        sum_prompt = templ_sum_en
        score_prompt = templ_score_en
    elif language == "zh":
        sum_prompt = templ_sum_zh
        score_prompt = templ_score_zh
    else:
        print("Unknown language option")
        exit(0)

    request_url = args.request_url
    eval_model = args.eval_model

    sum_result_file = args.sum_result_file
    transcript_file = args.transcript_file
    eval_report_file = args.eval_report_file
    
    skip_transcribe = args.skip_transcribe
    skip_summarize = args.skip_summarize
    skip_evaluate = args.skip_evaluate

    audio_path = Path(args.audio_file)
    if args.result_dir is None:
        result_dir = audio_path.with_suffix('')
    else:
        result_dir = Path(args.result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    t_start = t_end = s_start = s_end = e_start = e_end = None

    # transcribe
    if not skip_transcribe:
        t_start = time.time()
        transcript = transcribe(asr_model, str(audio_path))
        t_end = time.time()
        try:
            with open(result_dir / transcript_file, 'w', encoding='utf-8') as output_file:
                output_file.write(transcript)
            print(f"transcript saved to {result_dir / transcript_file}")
        except Exception as e:
            print(f"Failed to save transcript: {e}")
            sys.exit(1)

    # summarize
    if not skip_summarize:
        if skip_transcribe:
            transcript_path = result_dir / transcript_file
            if not transcript_path.exists():
                print(f"transcript_file not found at {transcript_path}, please make sure transcript exists before running skip_transcribe")
                sys.exit(1)
            try:
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    transcript = f.read()
            except Exception as e:
                print(f"Failed to read transcript: {e}")
                sys.exit(1)
        sum_prompt_filled = sum_prompt.format(transcript=transcript)
        message = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": sum_prompt_filled}
        ]
        s_start = time.time()
        summary = summarize(sum_model, message, sum_provider)
        s_end = time.time()
        try:
            with open(result_dir / sum_result_file, 'w', encoding='utf-8') as output_file:
                output_file.write(summary)
            print(f"summary saved to {result_dir / sum_result_file}")
        except Exception as e:
            print(f"Failed to save summary: {e}")
            sys.exit(1)

    # evaluate
    if not skip_evaluate:
        if skip_transcribe:
            transcript_path = result_dir / transcript_file
            if not transcript_path.exists():
                print(f"transcript_file not found at {transcript_path}, please make sure transcript exists before running skip_transcribe")
                sys.exit(1)
            try:
                with open(transcript_path, 'r', encoding='utf-8') as f:
                    transcript = f.read()
            except Exception as e:
                print(f"Failed to read transcript: {e}")
                sys.exit(1)
        if skip_summarize:
            summary_path = result_dir / sum_result_file
            if not summary_path.exists():
                print(f"sum_result_file not found at {summary_path}, please make sure summary exists before running skip_summarize")
                sys.exit(1)
            try:
                with open(summary_path, 'r', encoding='utf-8') as f:
                    summary = f.read()
            except Exception as e:
                print(f"Failed to read summary: {e}")
                sys.exit(1)
        score_prompt_filled = score_prompt.format(summary=summary, transcript=transcript)
        e_start = time.time()
        result = evaluate(eval_model, score_prompt_filled, request_url)
        e_end = time.time()
        try:
            with open(result_dir / eval_report_file, 'w', encoding='utf-8') as output_file:
                output_file.write(result)
            print(f"Evaluation report saved to {result_dir / eval_report_file}")
        except Exception as e:
            print(f"Failed to save evaluation report: {e}")
            sys.exit(1)

    try:
        total_audio_length = get_audio_length_pydub(str(audio_path))
        print(f"Audio length: {total_audio_length:.2f} seconds")
    except Exception as e:
        print(f"Failed to get audio length: {e}")

    if t_start and t_end:
        print(f"Transcription time: {t_end-t_start:.2f} seconds")
    if s_start and s_end:
        print(f"Summarization time: {s_end-s_start:.2f} seconds")
    if e_start and e_end:
        print(f"Evaluation time: {e_end-e_start:.2f} seconds")

if __name__ == "__main__":
    main()
