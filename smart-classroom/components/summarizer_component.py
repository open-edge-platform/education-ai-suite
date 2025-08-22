from components.base_component import PipelineComponent
from components.llm.openvino.summarizer import Summarizer
from utils.config_loader import config
import logging
import time

logger = logging.getLogger(__name__)

class SummarizerComponent(PipelineComponent):

    def __init__(self, session_id, model_name, device, temperature=0.7):
        self.session_id = session_id
        self.summarizer = Summarizer(model_name=model_name, device=device, temperature=temperature, revision=None)

    def _get_message(self, input):
        return [
                {"role": "system", "content": f"{config.models.summarizer.system_prompt}"},
                {"role": "user", "content": f"{input}"}
            ]

    def process(self, input):
        prompt = self.summarizer.tokenizer.apply_chat_template(self._get_message(input), tokenize=False, add_generation_prompt=True)
        start = time.perf_counter()
        try:
            yield from self.summarizer.generate(prompt)
        finally:
            end = time.perf_counter()
            logger.info(f"Total inference time: {end - start:.2f} seconds")
        


