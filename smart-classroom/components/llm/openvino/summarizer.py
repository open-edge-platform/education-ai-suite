from components.llm.base_summarizer import BaseSummarizer
import openvino_genai as ov_genai
from transformers import AutoTokenizer
import logging, threading
from utils import ensure_model
from utils.ov_genai_util import YieldingTextStreamer
logger = logging.getLogger(__name__)

class Summarizer(BaseSummarizer):
    def __init__(self, model_name, device, temperature=0.7, revision=None):
        self.model_name = model_name
        self.device = device
        self.temperature = temperature
        self.tokenizer = AutoTokenizer.from_pretrained(ensure_model.get_model_path())
        self.model = ov_genai.LLMPipeline(ensure_model.get_model_path(), device=device)

    def generate(self, prompt):
        streamer = YieldingTextStreamer(self.tokenizer)
        threading.Thread(target=lambda: self.model.generate(prompt, streamer=streamer), daemon=True).start()
        return streamer.stream()
