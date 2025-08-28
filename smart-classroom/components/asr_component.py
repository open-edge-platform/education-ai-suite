from components.base_component import PipelineComponent
import os
from utils.config_loader import config
from utils.storage_manager import StorageManager
from utils.runtime_config_loader import RuntimeConfig
from components.asr.openai.whisper import Whisper
from components.asr.funasr.paraformer import Paraformer

DELETE_CHUNK_AFTER_USE =  config.pipeline.delete_chunks_after_use

class ASRComponent(PipelineComponent):

    _model = None
    _config = None

    def __init__(self, session_id, provider="openai", model_name="whisper-small", device="cpu", temperature=0.0):

        self.session_id = session_id
        self.temperature = temperature
        provider, model_name = provider.lower(), model_name.lower()

        config = (provider, model_name, device)

        # Reload only if config changed
        if ASRComponent._model is None or ASRComponent._config != config:
            if provider == "openai" and "whisper" in model_name:
                ASRComponent._model = Whisper(model_name, device, None)
            elif provider == "funasr" and "paraformer" in model_name:
                ASRComponent._model = Paraformer(model_name, device, None)
            else:
                raise ValueError(f"Unsupported ASR provider/model: {provider}/{model_name}")
            ASRComponent._config = config

        self.asr = ASRComponent._model

    def process(self, input_generator):

        project_config = RuntimeConfig.get_section("Project")
        project_path = os.path.join(project_config.get("location"), project_config.get("name"), self.session_id)
        StorageManager.save(os.path.join(project_path, "transcription.txt"), "", append=False)
      
        for chunk_data in input_generator:
            chunk_path = chunk_data["chunk_path"]
            transcribed_text = self.asr.transcribe(chunk_path, temperature=self.temperature)

            if os.path.exists(chunk_data["chunk_path"]) and DELETE_CHUNK_AFTER_USE:
                os.remove(chunk_data["chunk_path"])

            StorageManager.save_async(os.path.join(project_path, "transcription.txt"), transcribed_text["text"], append=True)

            yield {
                **chunk_data,  # keep all chunk metadata
                "text": transcribed_text["text"]
            }
            