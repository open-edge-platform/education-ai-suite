from components.pipeline_comoponent import PipelineComponent
from components.asr.openvino.whisper import Whisper

class ASRComponent(PipelineComponent):
    def __init__(self, model="Whisper-small", device="cpu"): #Either Paraformer as model or Whisper
        #self.asr = Whisper(model=model,device="cpu") or Paraformer()
        pass


    def process(self, audio_path):
        #text = self.asr.transcribe(audio_path)
        #return the text
        pass