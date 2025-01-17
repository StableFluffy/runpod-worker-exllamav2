import os
from exllamav2.model import ExLlamaV2, ExLlamaV2Cache, ExLlamaV2Config, ExLlamaV2Lora
from exllamav2.tokenizer import ExLlamaV2Tokenizer
from exllamav2.generator import (
    ExLlamaV2Sampler,
    ExLlamaV2StreamingGenerator,
)
from download_model import download_model
import time

MODEL_NAME = os.environ.get("MODEL_NAME")
MODEL_REVISION = os.environ.get("MODEL_REVISION", "main")
LORA_NAME = os.environ.get("LORA_ADAPTER_NAME", None)
LORA_REVISION = os.environ.get("LORA_ADAPTER_REVISION", "main")
MODEL_BASE_PATH = os.environ.get("MODEL_BASE_PATH", "/runpod-volume/")


class Predictor:
    def setup(self):
        # Model moved to network storage
        model_directory = f"{MODEL_BASE_PATH}{MODEL_NAME.split('/')[1]}"

        # check if model directory exists. else, download model
        if not os.path.isdir(model_directory):
            print("Downloading model...")
            try:
                download_model(model_name=MODEL_NAME, model_revision=MODEL_REVISION)
                if LORA_NAME is not None:
                    download_model(model_name=LORA_NAME, model_revision=LORA_REVISION)
            except Exception as e:
                print(f"Error downloading model: {e}")
                # delete model directory if it exists
                if os.path.isdir(model_directory):
                    os.system(f"rm -rf {model_directory}")
                raise e

        config = ExLlamaV2Config()
        config.model_dir = model_directory
        config.prepare()
        config.max_seq_len = 4096

        self.tokenizer = ExLlamaV2Tokenizer(config)
        self.model = ExLlamaV2(config)
        self.model.load()
        self.cache = ExLlamaV2Cache(self.model)
        self.settings = ExLlamaV2Sampler.Settings()

        # Load LORA adapter if specified
        self.lora_adapter = None
        if LORA_NAME is not None:
            lora_directory = f"{MODEL_BASE_PATH}{LORA_NAME.split('/')[1]}"
            self.lora_adapter = ExLlamaV2Lora.from_directory(self.model, lora_directory)

    def predict(self, settings):
        ### Set the generation settings
        self.settings.temperature = settings["temperature"]
        self.settings.top_p = settings["top_p"]
        self.settings.top_k = settings["top_k"]
        self.settings.token_repetition_penalty = settings["token_repetition_penalty"]
        self.settings.token_repetition_range = settings["token_repetition_range"]
        self.settings.token_repetition_decay = settings["token_repetition_decay"]

        output = None
        time_begin = time.time()
        output = self.streamGenerate(settings["prompt"], settings["max_new_tokens"])
        for chunk in output:
            yield chunk
        time_end = time.time()
        print(f"⏱️ Time taken for inference: {time_end - time_begin} seconds")

    def streamGenerate(self, prompt, max_new_tokens):
        input_ids = self.tokenizer.encode(prompt)
        generator = ExLlamaV2StreamingGenerator(self.model, self.cache, self.tokenizer)
        generator.warmup()

        generator.begin_stream(input_ids, self.settings, loras=self.lora_adapter)
        generated_tokens = 0

        while True:
            chunk, eos, _ = generator.stream()
            generated_tokens += 1
            yield chunk

            if eos or generated_tokens == max_new_tokens or chunk == "</s>":
                break
