from components.base_component import PipelineComponent
import os
from utils.config_loader import config

DELETE_CHUNK_AFTER_USE =  config.pipeline.delete_chunks_after_use # seconds

class ASRComponent(PipelineComponent):
    def __init__(self, provider="openai", model="whisper-small", device="cpu", temperature = 0.0): 

        provider = provider.lower()
        model = model.lower()

        if provider == "openai" and "whisper" in model:
            from components.asr.openai.whisper import Whisper
            self.asr =  Whisper(model, device, None)
        elif provider == "funasr" and "paraformer" in model:
            from components.asr.funasr.paraformer import Paraformer
            self.asr =  Paraformer(model, device, None)
        else:
            raise ValueError(f"Unsupported ASR provider/model: {provider}/{model}")

        self.temperature = temperature

    def process(self, input_generator):

        for chunk_data in input_generator:
            chunk_path = chunk_data["chunk_path"]
            transcribed_text = self.asr.transcribe(chunk_path, temperature=self.temperature)

            if os.path.exists(chunk_data["chunk_path"]) and DELETE_CHUNK_AFTER_USE:
                os.remove(chunk_data["chunk_path"])

            yield {
                **chunk_data,  # keep all chunk metadata
                "text": transcribed_text["text"]
            }