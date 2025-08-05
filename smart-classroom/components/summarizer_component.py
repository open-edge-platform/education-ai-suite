from components.base_component import PipelineComponent
from components.asr.openvino.whisper import Whisper

class SummarizerComponent(PipelineComponent):
    def __init__(self, model_name=..., revision=..., device="cpu"):
        # Load model
        pass

    def summarize(self, prompt: str) -> str:
        pass