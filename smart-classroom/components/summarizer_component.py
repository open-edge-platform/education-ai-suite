from components.base_component import PipelineComponent

class SummarizerComponent(PipelineComponent):
    def __init__(self, session_id, model_name=..., revision=..., device="cpu"):
        # Load model
        pass

    def summarize(self, prompt: str) -> str:
        pass