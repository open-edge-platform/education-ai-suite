from components.base_component import PipelineComponent
from components.llm.openvino.summarizer import Summarizer as OvSummarizer
from components.llm.ipex.summarizer import Summarizer as IpexSummarizer
from utils.runtime_config_loader import RuntimeConfig
from utils.config_loader import config
from utils.storage_manager import StorageManager
import logging, os
import time

logger = logging.getLogger(__name__)

class SummarizerComponent(PipelineComponent):
    _model = None
    _config = None

    def __init__(self, session_id, provider, model_name, device, temperature=0.7):
        self.session_id = session_id
        provider = provider.lower()
        config = (provider, model_name, device) 

        # Reload only if config changed
        if SummarizerComponent._model is None or SummarizerComponent._config != config:
            if provider == "openvino":
                SummarizerComponent._model = OvSummarizer(
                    model_name=model_name,
                    device=device,
                    temperature=temperature,
                    revision=None
                )
            elif provider == "ipex":
                SummarizerComponent._model = IpexSummarizer(
                    model_name=model_name,
                    device=device.lower()
                )
            else:
                raise ValueError(f"Unsupported summarizer provider: {provider}")

            SummarizerComponent._config = config

        self.summarizer = SummarizerComponent._model

    def _get_message(self, input):

        lang_prompt = vars(config.models.summarizer.system_prompt)
        logger.debug(f"System Prompt: {lang_prompt.get(config.models.summarizer.language)}")

        return [
                {"role": "system", "content": f"{lang_prompt.get(config.models.summarizer.language)}"},
                {"role": "user", "content": f"{input}"}
            ]

    def process(self, input):
        project_config = RuntimeConfig.get_section("Project")
        project_path = os.path.join(project_config.get("location"), project_config.get("name"), self.session_id)
        StorageManager.save(os.path.join(project_path, "summary.md"), "", append=False)
        prompt = self.summarizer.tokenizer.apply_chat_template(self._get_message(input), tokenize=False, add_generation_prompt=True)
        start = time.perf_counter()
        try:
            for token in self.summarizer.generate(prompt):
                StorageManager.save_async(os.path.join(project_path, "summary.md"), token, append=True)
                yield token
        finally:
            end = time.perf_counter()
            logger.info(f"Total inference time: {end - start:.2f} seconds")
        


