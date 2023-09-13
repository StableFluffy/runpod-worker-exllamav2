import torch
import logging, os, glob
from exllamav2.model import ExLlamaV2, ExLlamaV2Cache, ExLlamaV2Config
from exllamav2.tokenizer import ExLlamaV2Tokenizer
from exllamav2.generator import ExLlamaV2BaseGenerator
from schema import InferenceSettings
from download_model import download_model

MODEL_NAME = os.environ.get("MODEL_NAME")
MODEL_REVISION = os.environ.get("MODEL_REVISION", "main")
MODEL_BASE_PATH = os.environ.get("MODEL_BASE_PATH", "/runpod-volume/")


class Predictor:
    def setup(self):
        # Model moved to network storage
        model_directory = f"{MODEL_BASE_PATH}{MODEL_NAME.split('/')[1]}"

        # check if model directory exists. else, download model
        if not os.path.isdir(model_directory):
            print("Downloading model...")
            try:
                download_model()
            except Exception as e:
                print(f"Error downloading model: {e}")
                # delete model directory if it exists
                if os.path.isdir(model_directory):
                    os.rmdir(model_directory)
                raise e

        tokenizer_path = os.path.join(model_directory, "tokenizer.model")
        model_config_path = os.path.join(model_directory, "config.json")
        st_pattern = os.path.join(model_directory, "*.safetensors")
        model_path = glob.glob(st_pattern)[0]

        config = ExLlamaV2Config(model_config_path)  # create config from config.json
        config.model_path = model_path  # supply path to model weights file

        """Load the model into memory to make running multiple predictions efficient"""
        print("Loading tokenizer...")

        self.tokenizer = ExLlamaV2Tokenizer(
            tokenizer_path
        )  # create tokenizer from tokenizer model file

        print("Loading model...")

        self.model = ExLlamaV2(config)  # create ExLlamaV2 instance and load the weights

        print("Creating cache...")
        self.cache = ExLlamaV2Cache(self.model)  # create cache for inference

        print("Creating generator...")
        self.generator = ExLlamaV2BaseGenerator(
            model=self.model, tokenizer=self.tokenizer, cache=self.cache
        )  # create generator
        # Configure generator
        # self.generator.disallow_tokens([self.tokenizer.eos_token_id])

        self.inference_settings = InferenceSettings()

        self.generator.settings.token_repetition_penalty_max = (
            self.inference_settings.token_repetition_penalty
        )
        self.generator.settings.temperature = self.inference_settings.temperature
        self.generator.settings.top_p = self.inference_settings.top_p
        self.generator.settings.typical = self.inference_settings.typical_p
        self.generator.settings.top_k = self.inference_settings.top_k
        self.generator.settings.beams = self.inference_settings.num_beams
        self.generator.settings.beam_length = self.inference_settings.length_penalty

    def predict(self, settings):
        return self.generate_to_eos(settings)

    def generate_to_eos(self, settings):
        self.generator.end_beam_search()

        # Update generator settings
        self.inference_settings = InferenceSettings(**settings)

        self.generator.settings.token_repetition_penalty_max = (
            self.inference_settings.token_repetition_penalty
        )
        self.generator.settings.temperature = self.inference_settings.temperature
        self.generator.settings.top_p = self.inference_settings.top_p
        self.generator.settings.typical = self.inference_settings.typical_p
        self.generator.settings.top_k = self.inference_settings.top_k
        self.generator.settings.beams = self.inference_settings.num_beams
        self.generator.settings.beam_length = self.inference_settings.length_penalty

        ids = self.tokenizer.encode(self.inference_settings.prompt)
        num_res_tokens = ids.shape[-1]  # Decode from here
        self.generator.gen_begin(ids)

        text = ""
        new_text = ""

        self.generator.begin_beam_search()
        for i in range(self.inference_settings.max_new_tokens):
            gen_token = self.generator.beam_search()
            if gen_token.item() == self.tokenizer.eos_token_id:
                return new_text

            num_res_tokens += 1
            text = self.tokenizer.decode(
                self.generator.sequence_actual[:, -num_res_tokens:][0]
            )
            new_text = text[len(self.inference_settings.prompt) :]
            for sequence in self.inference_settings.reverse_prompt:
                if new_text.lower().endswith(sequence.lower()):
                    return new_text[: -len(sequence)]

        return new_text
