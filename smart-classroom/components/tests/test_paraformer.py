import unittest
from unittest.mock import patch, MagicMock
from components.asr.funasr.paraformer import Paraformer, FUNASR_MODEL_LIST

class TestParaformer(unittest.TestCase):
    @patch("components.asr.funasr.paraformer.AutoModel")
    def test_initialization(self, MockAutoModel):
        mock_model = MagicMock()
        MockAutoModel.return_value = mock_model

        paraformer = Paraformer(FUNASR_MODEL_LIST[0], device="cpu", enable_diarization=False)
        self.assertEqual(paraformer.model, mock_model)

        with self.assertRaises(Exception):
            Paraformer("invalid-model", device="cpu")

    @patch("components.asr.funasr.paraformer.AutoModel")
    def test_transcribe(self, MockAutoModel):
        mock_model = MagicMock()
        mock_model.generate.return_value = [{"key": "audio", "text": "transcribed text"}]
        MockAutoModel.return_value = mock_model

        paraformer = Paraformer(FUNASR_MODEL_LIST[0], device="cpu")
        result = paraformer.transcribe("test_audio.wav")

        mock_model.generate.assert_called_once_with(input="test_audio.wav")
        self.assertEqual(result, "transcribed text")

        mock_model.generate.return_value = []
        with self.assertRaises(Exception):
            paraformer.transcribe("test_audio.wav")

if __name__ == "__main__":
    unittest.main()