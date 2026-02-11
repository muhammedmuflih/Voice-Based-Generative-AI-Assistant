import os
import logging
import sqlite3
import datetime
from flask import Flask, render_template, request, jsonify, session
from flask_session import Session
from utils.llm import LanguageModel
from utils.stt import SpeechToText 
from config import LOG_LEVEL, LOG_FILE

# ==========================================
# CONFIGURATION & SETUP
# ==========================================

# Create necessary directories
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("temp_uploads", exist_ok=True)
os.makedirs("flask_session", exist_ok=True)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Configure session
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "flask_session"
Session(app)

# Initialize AI Models
llm = LanguageModel()
stt = SpeechToText()

# ==========================================
# DATABASE FUNCTIONS (Internal)
# ==========================================

DB_NAME = "chat_history.db"

def init_db():
    """Initialize the database tables."""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Table for conversation sessions
        c.execute('''CREATE TABLE IF NOT EXISTS conversations
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      title TEXT, 
                      created_at TIMESTAMP)''')
        # Table for messages within a session
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      conversation_id INTEGER, 
                      sender TEXT, 
                      content TEXT, 
                      timestamp TIMESTAMP,
                      FOREIGN KEY(conversation_id) REFERENCES conversations(id))''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

def create_conversation(first_message):
    """Start a new conversation thread."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Use first 30 chars of message as title
    title = first_message[:30] + "..." if len(first_message) > 30 else first_message
    c.execute("INSERT INTO conversations (title, created_at) VALUES (?, ?)", 
              (title, datetime.datetime.now()))
    conv_id = c.lastrowid
    conn.commit()
    conn.close()
    return conv_id

def add_message(conversation_id, sender, content):
    """Save a message to a specific conversation."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO messages (conversation_id, sender, content, timestamp) VALUES (?, ?, ?, ?)",
              (conversation_id, sender, content, datetime.datetime.now()))
    conn.commit()
    conn.close()

def get_all_conversations():
    """Get list of all conversations for the sidebar."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM conversations ORDER BY created_at DESC")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def get_messages_by_conversation(conversation_id):
    """Get full chat history for a specific session."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows

def delete_conversation_db(conversation_id):
    """Delete a conversation and its messages."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    c.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()

# Initialize DB on startup
init_db()

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/new_chat', methods=['POST'])
def new_chat():
    """Reset current session to start fresh"""
    session.pop('current_chat_id', None)
    llm.clear_history()
    return jsonify({'status': 'success'})

@app.route('/history', methods=['GET'])
def get_history_list():
    """Get list of past conversations for the sidebar"""
    try:
        chats = get_all_conversations()
        return jsonify({'chats': chats})
    except Exception as e:
        return jsonify({'chats': []})

@app.route('/history/<int:chat_id>', methods=['GET'])
def load_chat_history(chat_id):
    """Load specific chat messages"""
    try:
        messages = get_messages_by_conversation(chat_id)
        session['current_chat_id'] = chat_id
        
        # Reload LLM context
        llm.clear_history() 
        for msg in messages:
            if msg['sender'] == 'user':
                llm.conversation_history.append({"role": "user", "parts": [msg['content']]})
            else:
                llm.conversation_history.append({"role": "model", "parts": [msg['content']]})
                
        return jsonify({'messages': messages})
    except Exception as e:
        logger.error(f"Error loading history: {e}")
        return jsonify({'messages': []})

@app.route('/delete_chat/<int:chat_id>', methods=['DELETE'])
def delete_chat(chat_id):
    """Delete a conversation"""
    try:
        delete_conversation_db(chat_id)
        if session.get('current_chat_id') == chat_id:
            session.pop('current_chat_id', None)
            llm.clear_history()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages"""
    user_message = request.json.get('message', '')
    
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    
    try:
        # Check if we have an active chat ID, if not create one
        chat_id = session.get('current_chat_id')
        if not chat_id:
            chat_id = create_conversation(user_message)
            session['current_chat_id'] = chat_id
        
        # Save User Message to DB
        add_message(chat_id, 'user', user_message)

        # Generate Response
        response = llm.generate_response(user_message)
        
        # Save Assistant Message to DB
        add_message(chat_id, 'assistant', response)
        
        return jsonify({
            'response': response,
            'status': 'success',
            'chat_id': chat_id
        })
    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/voice', methods=['POST'])
def voice_command():
    """Process voice commands"""
    if 'audio_data' not in request.files:
        return jsonify({'error': 'No audio file uploaded'}), 400

    audio_file = request.files['audio_data']
    if audio_file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    temp_path = os.path.join("temp_uploads", "temp_audio.webm") 
    
    try:
        audio_file.save(temp_path)
        user_input = stt.listen_from_file(temp_path)
        
        if user_input:
            # Handle DB logic same as /chat
            chat_id = session.get('current_chat_id')
            if not chat_id:
                chat_id = create_conversation(user_input)
                session['current_chat_id'] = chat_id
            
            add_message(chat_id, 'user', user_input)
            
            response_text = llm.generate_response(user_input)
            
            add_message(chat_id, 'assistant', response_text)
            
            return jsonify({
                'response': response_text,
                'status': 'success',
                'transcription': user_input
            })
        else:
            return jsonify({
                'response': "Sorry, I couldn't understand the audio.",
                'status': 'failure',
                'transcription': ''
            })

    except Exception as e:
        logger.error(f"Error processing voice: {str(e)}")
        return jsonify({'error': str(e), 'status': 'error'}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/clear', methods=['POST'])
def clear_conversation():
    session.pop('current_chat_id', None)
    llm.clear_history()
    return jsonify({'status': 'success'})

if __name__ == '__main__':
    # Run the web server
    app.run(debug=True, host='0.0.0.0', port=5000)