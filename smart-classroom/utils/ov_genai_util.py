import queue
import openvino_genai as ov_genai

class YieldingTextStreamer(ov_genai.StreamerBase):
    def __init__(self, tokenizer, skip_special_tokens=True):
        super().__init__()
        self.tokenizer = tokenizer
        self.skip_special_tokens = skip_special_tokens
        self._queue = queue.Queue()
        self._finished = False

        # Hugging Face style incremental decoding
        self._token_cache = []
        self._print_len = 0

    def put(self, token_id) -> bool:
        # Add token to cache
        self._token_cache.append(token_id)

        # Decode current cached tokens
        text = self.tokenizer.decode(self._token_cache, skip_special_tokens=self.skip_special_tokens)

        # Only get the newly decoded part since last emission
        new_text = text[self._print_len:]

        # Hugging Face logic: emit if the last character is safe (space, newline, or CJK)
        if new_text and self._is_safe_to_emit(new_text):
            self._queue.put(new_text)
            self._print_len += len(new_text)

        return False  # continue generation

    def end(self):
        # Flush any remaining text
        if self._token_cache:
            text = self.tokenizer.decode(self._token_cache, skip_special_tokens=self.skip_special_tokens)
            remaining_text = text[self._print_len:]
            if remaining_text:
                self._queue.put(remaining_text)

        # Signal completion
        self._finished = True
        self._queue.put(None)

        # Reset internal state
        self._token_cache = []
        self._print_len = 0

    def stream(self):
        """Yield tokens as they are generated"""
        while True:
            token = self._queue.get()
            if token is None:
                break
            yield token

    # ---------------- Hugging Face-inspired helper methods ---------------- #
    def _is_safe_to_emit(self, text: str) -> bool:
        """
        Returns True if the text can be safely emitted without cutting multi-byte CJK or UTF-8 characters.
        Emit if last char is CJK, whitespace, or newline.
        """
        last_char = text[-1]
        cp = ord(last_char)
        if self._is_cjk(cp):
            return True
        if last_char.isspace() or last_char == "\n":
            return True
        # Otherwise wait for more tokens to form a complete word/char
        return False

    def _is_cjk(self, cp: int) -> bool:
        """
        Check if Unicode codepoint is Chinese/Japanese/Korean (CJK).
        Adapted from Hugging Face TextStreamer.
        """
        return (
            (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0x20000 <= cp <= 0x2A6DF)
            or (0x2A700 <= cp <= 0x2B73F)
            or (0x2B740 <= cp <= 0x2B81F)
            or (0x2B820 <= cp <= 0x2CEAF)
            or (0xF900 <= cp <= 0xFAFF)
            or (0x2F800 <= cp <= 0x2FA1F)
        )
