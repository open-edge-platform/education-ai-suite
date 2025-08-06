from components.summarizer.base_summarizer import BaseSummarizer

class Summarizer(BaseSummarizer):
    def __init__(self, model_name=..., revision=..., device="cpu"):
       # Load model
       pass

    def generate(self, prompt: str) -> str:
        #Summarize
        pass