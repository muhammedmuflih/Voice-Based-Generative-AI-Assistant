import whisper
import os
import logging

logger = logging.getLogger(__name__)

class SpeechToText:
    """
    Multilingual Speech-to-Text using OpenAI Whisper
    Automatically detects and transcribes in the spoken language.
    """

    def __init__(self, model_size="medium"):
        """
        Model sizes:
        tiny | base | small | medium | large
        Use 'large' for best multilingual accuracy
        """
        logger.info(f"Loading Whisper model: {model_size}")
        self.model = whisper.load_model(model_size)
        logger.info("Whisper model loaded successfully")

    def listen_from_file(self, audio_file_path: str) -> str:
        """
        Transcribe audio and return text in detected language
        """

        if not audio_file_path or not os.path.exists(audio_file_path):
            logger.error("Audio file not found")
            return ""

        try:
            logger.info("Preparing audio for Whisper")

            # Load and preprocess audio
            audio = whisper.load_audio(audio_file_path)
            audio = whisper.pad_or_trim(audio)

            # Convert audio to log-Mel spectrogram
            mel = whisper.log_mel_spectrogram(audio).to(self.model.device)

            # Detect spoken language
            _, probs = self.model.detect_language(mel)
            detected_language = max(probs, key=probs.get)

            logger.info(f"Detected language: {detected_language}")

            # Decode speech using detected language
            options = whisper.DecodingOptions(language=detected_language, fp16=False)
            result = whisper.decode(self.model, mel, options)

            text = result.text.strip()

            logger.info(f"Transcription: {text}")

            return text

        except Exception as e:
            logger.exception(f"Whisper STT Error: {e}")
            return ""