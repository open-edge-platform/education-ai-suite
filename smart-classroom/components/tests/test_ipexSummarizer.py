import unittest
from unittest.mock import patch, MagicMock
from components.summarizer.ipex.summarizer import Summarizer

TEST_MODEL = "Qwen/Qwen2.5-7B-Instruct"

class TestSummarizer(unittest.TestCase):
    @patch("components.summarizer.ipex.summarizer.AutoModelForCausalLM")
    @patch("components.summarizer.ipex.summarizer.torch")
    @patch("transformers.AutoTokenizer")
    def test_init_huggingface(self, mock_tokenizer_cls, mock_torch, mock_model):
        mock_tokenizer = MagicMock()
        mock_tokenizer_cls.from_pretrained.return_value = mock_tokenizer
        mock_model.from_pretrained.return_value = MagicMock(half=MagicMock(return_value=MagicMock(to=MagicMock(return_value="model"))))
        summarizer = Summarizer(TEST_MODEL, device="xpu", model_hub="huggingface")
        self.assertEqual(summarizer.device, "xpu")
        self.assertIsNotNone(summarizer.model)
        self.assertIsNotNone(summarizer.tokenizer)

    @patch("components.summarizer.ipex.summarizer.AutoModelForCausalLM")
    @patch("components.summarizer.ipex.summarizer.torch")
    def test_init_invalid_modelhub(self, mock_torch, mock_model):
        summarizer = Summarizer(TEST_MODEL, model_hub="invalidhub")
        self.assertIsNone(summarizer.model)
        self.assertIsNone(summarizer.tokenizer)

    @patch("components.summarizer.ipex.summarizer.AutoModelForCausalLM")
    @patch("components.summarizer.ipex.summarizer.torch")
    @patch("transformers.AutoTokenizer")
    def test_generate(self, mock_tokenizer_cls, mock_torch, mock_model):
        mock_tokenizer = MagicMock()
        mock_tokenizer.apply_chat_template.return_value = "prompt"
        mock_tokenizer.batch_decode.return_value = ["summary"]
        mock_tokenizer_cls.from_pretrained.return_value = mock_tokenizer
        mock_model_instance = MagicMock()
        mock_model_instance.generate.return_value = mock_torch.tensor([[1,2,3,4]])
        mock_model.from_pretrained.return_value = mock_model_instance
        mock_model_instance.half.return_value = mock_model_instance
        mock_model_instance.to.return_value = mock_model_instance

        summarizer = Summarizer(TEST_MODEL)
        summarizer.tokenizer = mock_tokenizer
        summarizer.model = mock_model_instance
        mock_torch.inference_mode.return_value.__enter__.return_value = None
        mock_torch.inference_mode.return_value.__exit__.return_value = None
        mock_torch.xpu.synchronize.return_value = None
        mock_torch.tensor.return_value = mock_model_instance.generate.return_value
        # Mock model_inputs
        model_inputs = MagicMock()
        model_inputs.input_ids = [[1,2]]
        summarizer.tokenizer.__call__ = MagicMock(return_value=model_inputs)
        model_inputs.to.return_value = model_inputs

        result = summarizer.generate("test prompt")
        self.assertEqual(result, "summary")

    @patch("components.summarizer.ipex.summarizer.AutoModelForCausalLM")
    @patch("components.summarizer.ipex.summarizer.torch")
    def test_generate_with_uninitialized_model(self, mock_torch, mock_model):
        summarizer = Summarizer(TEST_MODEL, model_hub="invalidhub")
        result = summarizer.generate("test prompt")
        self.assertEqual(result, "")

if __name__ == "__main__":
    unittest.main()
