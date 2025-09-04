## Prepare QnA service API keys

1. Login https://deepseek.intel.com/
2. Go to Personal Settings - Account
3. Show and get API keys - JWT Token
4. Replace `{your JWT token}` in `evaluate.py`


## Evaluate
```
cd education-ai-suite/smart-classroom
# read models from config.yaml
python .\evaluation\evaluate.py --audio_file <audio_file>

# OR specify via command line options
python .\evaluation\evaluate.py --audio_file <audio_file> --asr_model <asr_model_name> --sum_model <sum_model_name> --sum_provider <openvino/ipex> --language <en/zh>
```

The script does transcription -> summarization -> summary evaluation. To skip steps, for example skip transcription and summarization (do evaluation only), try
```
python .\evaluation\evaluate.py --audio_file <audio_file> --skip_transcribe --skip_summarize
```