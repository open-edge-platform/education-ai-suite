from components.summarizer.base_summarizer import BaseSummarizer
from ipex_llm.transformers import AutoModelForCausalLM
import torch


class Summarizer(BaseSummarizer):
    def __init__(self, model_name, device="xpu", model_hub="huggingface"):
        if model_hub == "huggingface":
            from transformers import AutoTokenizer
        elif model_hub == "modelscope":
            from modelscope import AutoTokenizer
        else:
            raise Exception(f"Invalid model_hub {model_hub}, should be huggingface or modelscope")
        
        # Load model
        self.model = AutoModelForCausalLM.from_pretrained(model_name,
                                                load_in_4bit=True,
                                                optimize_model=True,
                                                trust_remote_code=True,
                                                use_cache=True,
                                                model_hub=model_hub)
        self.device = device
        self.model = self.model.half().to(self.device)

        self.tokenizer = AutoTokenizer.from_pretrained(model_name,
                                              trust_remote_code=True)
           

    def generate(self, prompt: str, max_new_tokens: int = 512) -> str:
        #Summarize
        response = ""
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
        return response