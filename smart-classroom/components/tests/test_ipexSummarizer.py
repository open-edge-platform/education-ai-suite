import unittest
from unittest.mock import patch, MagicMock
from components.summarizer.ipex.summarizer import IPEXSummarizer

class TestIPEXSummarizer(unittest.TestCase):
    @patch("components.summarizer.ipex.summarizer.AutoModelForCausalLM")
    @patch("components.summarizer.ipex.summarizer.AutoTokenizer")
    def test_initialization(self, MockTokenizer, MockModel):
        mock_model = MagicMock()
        MockModel.from_pretrained.return_value = mock_model
        mock_tokenizer = MagicMock()
        MockTokenizer.from_pretrained.return_value = mock_tokenizer

        summarizer = IPEXSummarizer("test-model", device="cpu", model_hub="huggingface")
        self.assertEqual(summarizer.device, "cpu")
        self.assertEqual(summarizer.model, mock_model)
        self.assertEqual(summarizer.tokenizer, mock_tokenizer)

    @patch("components.summarizer.ipex.summarizer.AutoModelForCausalLM")
    @patch("components.summarizer.ipex.summarizer.AutoTokenizer")
    @patch("components.summarizer.ipex.summarizer.torch")
    def test_generate(self, MockTorch, MockTokenizer, MockModel):
        mock_model = MagicMock()
        MockModel.from_pretrained.return_value = mock_model
        mock_tokenizer = MagicMock()
        MockTokenizer.from_pretrained.return_value = mock_tokenizer

        mock_tokenizer.apply_chat_template.return_value = "formatted_prompt"
        mock_tokenizer.return_tensors = {"input_ids": MagicMock()}
        mock_tokenizer.batch_decode.return_value = ["generated_text"]
        mock_model.generate.return_value = MagicMock()

        summarizer = IPEXSummarizer("test-model", device="cpu", model_hub="huggingface")
        result = summarizer.generate("test prompt")

        mock_tokenizer.apply_chat_template.assert_called_once_with(
            "test prompt", tokenize=False, add_generation_prompt=True
        )
        mock_model.generate.assert_called_once()
        self.assertEqual(result, "generated_text")

if __name__ == "__main__":
    unittest.main()