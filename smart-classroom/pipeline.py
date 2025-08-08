from components.stream_reader import AudioStreamReader
from components.asr_component import ASRComponent
from utils.config_loader import config
import logging
from utils.session_manager import generate_session_id

logger = logging.getLogger(__name__)

TEMPERATURE =  config.models.asr.temperature # seconds
ASR_MODEL =  config.models.asr.name # seconds

class Pipeline:
    def __init__(self, session_id=None):
        logger.info("pipeline initialized")
        self.session_id = session_id or generate_session_id()
        # Bind models during construction
        self.transcription_pipeline = [
            AudioStreamReader(self.session_id),
            ASRComponent(self.session_id, model=ASR_MODEL, temperature=TEMPERATURE) 
        ]

    def run_transcription(self, audio_path: str):
        input_gen = ({"audio_path": audio_path} for _ in range(1))  # initial input generator

        for component in self.transcription_pipeline:
            input_gen = component.process(input_gen)

            # for chunk_data in input_gen:
            #     logger.debug(f"[DEBUG] Processed Chunk Data:\n{chunk_data}\n")

        return input_gen
