import unittest
import os
import requests
from unittest.mock import patch, MagicMock
from components.asr.funasr.paraformer import Paraformer, FUNASR_MODEL_LIST

EN_AUDIO_EXAMPLE_URL = "https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/asr_example_en.wav"
EN_AUDIO_TRANSCRIPT = "he tried to think how it could be"
ZH_AUDIO_EXAMPLE_URL = "https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/asr_example_zh.wav"
ZH_AUDIO_TRANSCRIPT = "欢迎大家来体验达摩院推出的语音识别模型"

TEST_MODEL = FUNASR_MODEL_LIST[0]

# a simplified calculation of WER, without proper tokenization, for simple test only
def calculate_wer(reference, hypothesis):
    """
    Calculate the Word Error Rate (WER) between the reference and hypothesis.
    """
    ref_words = reference.split()
    hyp_words = hypothesis.split()
    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]

    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1] == hyp_words[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = min(
                    d[i - 1][j] + 1,  # Deletion
                    d[i][j - 1] + 1,  # Insertion
                    d[i - 1][j - 1] + 1,  # Substitution
                )

    return d[len(ref_words)][len(hyp_words)] / len(ref_words)

class TestParaformer(unittest.TestCase):
    @patch("components.asr.funasr.paraformer.AutoModel")
    def test_initialization(self, MockAutoModel):
        mock_model = MagicMock()
        MockAutoModel.return_value = mock_model

        paraformer = Paraformer(TEST_MODEL, device="cpu", enable_diarization=False)
        self.assertEqual(paraformer.model, mock_model)

        with self.assertRaises(Exception):
            Paraformer("invalid-model", device="cpu")

    def test_transcribe_en(self):
        # Download the test audio file
        local_audio_path = "asr_example_en.wav"
        response = requests.get(EN_AUDIO_EXAMPLE_URL)
        response.raise_for_status()

        # Save the audio file locally
        with open(local_audio_path, "wb") as audio_file:
            audio_file.write(response.content)

        try:
            # Test the transcribe function with the real model
            paraformer = Paraformer(TEST_MODEL, device="cpu")
            result = paraformer.transcribe(local_audio_path)

            # Ground truth for the test audio
            expected_transcription = EN_AUDIO_TRANSCRIPT

            print("Model generated transcript: ", result)
            print("Expected transcript: ", expected_transcription)

            wer = calculate_wer(expected_transcription.lower(), result.lower())

            # Assertions
            self.assertLess(wer, 5, f"WER is too high: {wer:.2f}")
        finally:
            # Clean up the downloaded file
            if os.path.exists(local_audio_path):
                os.remove(local_audio_path)

    def test_transcribe_zh(self):
        # Download the test audio file
        local_audio_path = "asr_example_zh.wav"
        response = requests.get(ZH_AUDIO_EXAMPLE_URL)
        response.raise_for_status()

        # Save the audio file locally
        with open(local_audio_path, "wb") as audio_file:
            audio_file.write(response.content)

        try:
            # Test the transcribe function with the real model
            paraformer = Paraformer(TEST_MODEL, device="cpu")
            result = paraformer.transcribe(local_audio_path)

            # Ground truth for the test audio
            expected_transcription = ZH_AUDIO_TRANSCRIPT

            print("Model generated transcript: ", result)
            print("Expected transcript: ", expected_transcription)

            wer = calculate_wer(expected_transcription.lower(), result.lower())

            # Assertions
            self.assertLess(wer, 5, f"WER is too high: {wer:.2f}")
        finally:
            # Clean up the downloaded file
            if os.path.exists(local_audio_path):
                os.remove(local_audio_path)

if __name__ == "__main__":
    unittest.main()