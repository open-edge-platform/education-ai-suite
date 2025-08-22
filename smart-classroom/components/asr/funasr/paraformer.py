from components.asr.base_asr import BaseASR
from funasr import AutoModel

FUNASR_MODEL_LIST = [
    "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    "paraformer-zh",
    "paraformer-en",
    "paraformer-zh-online",
    "paraformer-zh-spk"
]

class Paraformer(BaseASR):
    def __init__(self, model_name, device="cpu", revision="v2.0.4", ncpu=1, enable_diarization=False):
        try:
            if model_name not in FUNASR_MODEL_LIST:
                raise ValueError(f"Invalid ASR model name {model_name}. Please refer to https://github.com/modelscope/FunASR/blob/main/model_zoo/readme.md for supported Paraformer models")
            
            # use same vad and punc model for different ASR models
            self.enable_diarization = enable_diarization
            if enable_diarization:
                self.model = AutoModel(model=model_name, model_revision=revision,
                                vad_model="fsmn-vad", vad_model_revision="v2.0.4",
                                punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch", punc_model_revision=revision,
                                spk_model="cam++", spk_model_revision="v2.0.2",
                                device=device, disable_update=True, ncpu=ncpu
                                )
            else:
                self.model = AutoModel(model=model_name, model_revision=revision,
                                vad_model="fsmn-vad", vad_model_revision="v2.0.4",
                                punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch", punc_model_revision=revision,
                                #   spk_model="cam++", spk_model_revision="v2.0.2",
                                device=device, disable_update=True, ncpu=ncpu
                                )
        except Exception as e:
            print(f"Error initializing Paraformer: {e}")
            self.model = None

    def transcribe(self, audio_path: str) -> str:
        try:
            if self.model is None:
                print("Model is not initialized.")
                return None
            res = self.model.generate(input=audio_path)
            # res [{'key': <input>, 'text': '...', , 'timestamp': [[], [], ...]}]
            if len(res) > 0:
                return res[0]["text"]
            else:
                print("ASR transcription failed")
                return None
        except Exception as e:
            print(f"Error during transcription: {e}")
            return None
        
    def transcribe_with_speaker_label(self, audio_path: str) -> dict:
        try:
            if not self.enable_diarization:
                print("Diarization is not enabled. Please init the model with enable_diarization=True")
                return None
            if self.model is None:
                print("Model is not initialized.")
                return None
            res = self.model.generate(input=audio_path)
            # res [{'key': <input>, 'text': '...', , 'timestamp': [[], [], ...], 'spk': <label>}]
            if len(res) > 0:
                return res[0]
            else:
                print("ASR transcription failed")
                return None
        except Exception as e:
            print(f"Error during transcription with speaker label: {e}")
            return None
