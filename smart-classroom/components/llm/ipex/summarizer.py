from components.summarizer.base_summarizer import BaseSummarizer
from ipex_llm.transformers import AutoModelForCausalLM
import torch
import threading

from utils.config_loader import config
import logging
logger = logging.getLogger(__name__)

from transformers import TextIteratorStreamer

class Summarizer(BaseSummarizer):
    def __init__(self, model_name, device="xpu"):
        if config.models.summarizer.model_hub is not None:
            model_hub = config.models.summarizer.model_hub
        else:
            model_hub = "huggingface"

        if model_hub == "huggingface":
            from transformers import AutoTokenizer
        elif model_hub == "modelscope":
            from modelscope import AutoTokenizer
        else:
            raise ValueError(f"Unsupported Model Hub: {model_hub}, should be huggingface or modelscope")

        # Load model
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name,
            load_in_4bit=True,
            optimize_model=True,
            trust_remote_code=True,
            use_cache=True,
            model_hub=model_hub
        )
        self.device = device
        self.model = self.model.half().to(self.device)

        self.tokenizer = AutoTokenizer.from_pretrained(
            model_name,
            trust_remote_code=True
        )

    def generate(self, prompt: str, stream: bool = True):
        #Summarize
        if config.models.summarizer.max_new_tokens is not None:
            max_new_tokens = config.models.summarizer.max_new_tokens
        else:
            max_new_tokens = 1024

        response = ""
        if not stream:
            try:
                with torch.inference_mode():
                    text = self.tokenizer.apply_chat_template(
                        prompt,
                        tokenize=False,
                        add_generation_prompt=True
                    )
                    model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)

                    generated_ids = self.model.generate(
                        model_inputs.input_ids,
                        max_new_tokens=max_new_tokens
                    )
                    torch.xpu.synchronize()
                    generated_ids = generated_ids.cpu()
                    generated_ids = [
                        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
                    ]

                    response = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            except Exception as e:
                logger.error(f"Error during generation: {e}")
            return response
        else:
            # Streaming output using TextIteratorStreamer
            try:
                with torch.inference_mode():
                    text = self.tokenizer.apply_chat_template(
                        prompt,
                        tokenize=False,
                        add_generation_prompt=True
                    )
                    model_inputs = self.tokenizer([text], return_tensors="pt").to(self.device)
                    streamer = TextIteratorStreamer(self.tokenizer, skip_special_tokens=True, skip_prompt=True)
                    gen_kwargs = dict(
                        input_ids=model_inputs.input_ids,
                        max_new_tokens=max_new_tokens,
                        streamer=streamer
                    )
                    
                    thread = threading.Thread(target=self.model.generate, kwargs=gen_kwargs)
                    thread.start()
                    return streamer
            except Exception as e:
                logger.error(f"Error during streaming generation: {e}")
                return None