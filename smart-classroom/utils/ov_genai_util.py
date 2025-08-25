import openvino_genai as ov_genai
import queue
import threading

class YieldingTextStreamer(ov_genai.StreamerBase):
    def __init__(self, tokenizer, skip_special_tokens=True):
        super().__init__()
        self.tokenizer = tokenizer
        self.skip_special_tokens = skip_special_tokens
        self._queue = queue.Queue()
        self._finished = False

    def put(self, token_id) -> bool:
        # Decode token_id to text
        text = self.tokenizer.decode([token_id], skip_special_tokens=self.skip_special_tokens)
        self._queue.put(text)
        return False  # continue generation

    def end(self):
        # Signal completion
        self._finished = True
        self._queue.put(None)

    def stream(self):
        """Yield tokens as they are generated"""
        while True:
            token = self._queue.get()
            if token is None:
                break
            yield token
