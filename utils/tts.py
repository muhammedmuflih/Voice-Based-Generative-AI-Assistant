import pyttsx3
from config import TTS_RATE, TTS_VOLUME

class TextToSpeech:
    def __init__(self):
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', TTS_RATE)
        self.engine.setProperty('volume', TTS_VOLUME)
        
        # Get available voices
        voices = self.engine.getProperty('voices')
        # Set a voice (you can change the index to select different voices)
        self.engine.setProperty('voice', voices[1].id)  # Index 1 is usually female
    
    def speak(self, text):
        """Convert text to speech"""
        print(f"Assistant: {text}")
        self.engine.say(text)
        self.engine.runAndWait()