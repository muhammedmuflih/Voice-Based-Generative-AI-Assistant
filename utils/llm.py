import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL, MAX_CONVERSATION_HISTORY

class LanguageModel:
    def __init__(self):
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel(GEMINI_MODEL)
        self.conversation_history = []
    
    def generate_response(self, prompt):
        """Generate a response using Gemini AI"""
        try:
            # Start a chat with conversation history
            chat = self.model.start_chat(history=self.conversation_history)
            response = chat.send_message(prompt)
            
            # Update conversation history
            self.conversation_history.append({"role": "user", "parts": [prompt]})
            self.conversation_history.append({"role": "model", "parts": [response.text]})
            
            # Limit conversation history
            if len(self.conversation_history) > MAX_CONVERSATION_HISTORY * 2:
                self.conversation_history = self.conversation_history[-MAX_CONVERSATION_HISTORY*2:]
            
            return response.text
            
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []