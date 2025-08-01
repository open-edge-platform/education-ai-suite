class Pipeline:
    def __init__(self, config):
        print("Development in progress: pipeline init")
        self.config = config
        self.steps = []

    def run(self, audio_path, asr_model_id, summarizer_model_id):
        print(f"Running pipeline for {audio_path} with {asr_model_id} and {summarizer_model_id}")
        return "Development in progress"