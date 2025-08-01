class BaseSummarizer:
   def __init__(self, model_name=..., revision=..., device="cpu"):
       #Abstract method for Summarizer Implementations
       pass

    def generate(self, prompt: str) -> str:
        #Abstract method for Summarizer Implementations
        pass