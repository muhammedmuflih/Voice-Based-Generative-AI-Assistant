/* =========================================================
   GLOBAL VARIABLES & CONFIG
========================================================= */
let mediaRecorder;
let audioChunks = [];
let micActive = false;
let soundEnabled = true;
let selectedVoice = null;

// Configuration
const MAX_MIC_TIME = 10000; // Auto-stop recording after 10 seconds
const SILENCE_TIMEOUT = 3000; // (Optional) Auto-stop on silence

// Check for Web Speech API support (for real-time text preview)
let recognition;
let isWebSpeechSupported = 'webkitSpeechRecognition' in window || 'SpeechRecognition' in window;

/* =========================================================
   INITIALIZATION
========================================================= */
$(document).ready(function () {
    // Button Event Listeners
    $('#send-btn').click(sendMessage);
    
    // Allow "Enter" key to send message
    $('#message-input').keypress(function(e) { 
        if (e.which === 13) sendMessage(); 
    });
    
    $('#voice-btn').click(toggleMicSession);
    $('#sound-toggle').click(toggleSound);
    
    // --- FIXED NEW CHAT LISTENER ---
    // Using e.preventDefault() ensures the button doesn't refresh the page
    $('#new-chat-btn').click(function(e) {
        e.preventDefault(); 
        startNewChat();
    });

    // Initialize Text-to-Speech Voices
    if (speechSynthesis.onvoiceschanged !== undefined) {
        speechSynthesis.onvoiceschanged = loadVoices;
    }
    loadVoices();
    
    // Load History sidebar on startup
    loadHistoryList();
});

/* =========================================================
   HISTORY & SIDEBAR MANAGEMENT
========================================================= */

// 1. Load the list of past conversations
function loadHistoryList() {
    $.get('/history', function(data) {
        const list = $('#history-list');
        list.empty();
        
        if (data.chats.length === 0) {
            list.append('<div style="padding:15px; color:#aaa; font-size:0.9em; text-align:center;">No history yet</div>');
            return;
        }

        data.chats.forEach(chat => {
            const item = $(`
                <div class="history-item" onclick="loadChat(${chat.id})">
                    <span class="chat-title">${escapeHtml(chat.title)}</span>
                    <i class="fa-solid fa-trash delete-chat" onclick="deleteChat(event, ${chat.id})"></i>
                </div>
            `);
            list.append(item);
        });
    });
}

// 2. Start a fresh conversation
function startNewChat() {
    $.post('/new_chat', function(res) {
        // Clear the chat window visually
        $('#chat-messages').html(`
            <div class="message system">
                <div class="message-content">
                    <p>✨ New Chat Started!</p>
                </div>
            </div>
        `);
        // Refresh the history list to remove any "active" styling (optional)
        loadHistoryList();
    });
}

// 3. Load a specific conversation from history
function loadChat(chatId) {
    $.get(`/history/${chatId}`, function(data) {
        $('#chat-messages').empty(); // Clear current view
        
        if (!data.messages || data.messages.length === 0) {
            $('#chat-messages').html('<div class="message system"><div class="message-content"><p>Empty conversation.</p></div></div>');
        } else {
            // Rebuild the chat bubbles
            data.messages.forEach(msg => {
                addMessage(msg.content, msg.sender === 'user');
            });
            // Scroll to bottom
            $('#chat-messages').scrollTop($('#chat-messages')[0].scrollHeight);
        }
    });
}

// 4. Delete a conversation
function deleteChat(e, chatId) {
    e.stopPropagation(); // Prevent the click from triggering 'loadChat'
    
    if(confirm("Are you sure you want to delete this conversation?")) {
        $.ajax({
            url: `/delete_chat/${chatId}`,
            type: 'DELETE',
            success: function() {
                loadHistoryList(); // Refresh sidebar
                // If we are currently viewing the deleted chat, we could clear the screen here
            }
        });
    }
}

/* =========================================================
   CHAT MESSAGING LOGIC
========================================================= */

function sendMessage() {
    const msg = $('#message-input').val().trim();
    if (!msg) return;

    // 1. Show User Message Immediately
    addMessage(msg, true);
    $('#message-input').val('');
    $('#typingIndicator').addClass('active');

    // 2. Send to Backend
    $.ajax({
        url: '/chat',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({ message: msg }),
        success: function (res) {
            $('#typingIndicator').removeClass('active');
            
            // 3. Show Assistant Response
            addMessage(res.response, false);
            speakText(res.response);
            
            // 4. Update History List (in case a new chat was just created)
            loadHistoryList();
        },
        error: () => {
            $('#typingIndicator').removeClass('active');
            addMessage("Error: Could not reach the server.", false);
        }
    });
}

function addMessage(text, isUser) {
    const cls = isUser ? 'user' : 'assistant';
    $('#chat-messages').append(`
        <div class="message ${cls}">
            <div class="message-content">
                <p>${escapeHtml(text)}</p>
            </div>
        </div>
    `);
    // Auto-scroll to the newest message
    $('#chat-messages').scrollTop($('#chat-messages')[0].scrollHeight);
}

/* =========================================================
   VOICE RECORDING LOGIC
========================================================= */

async function startMicSession() {
    micActive = true;
    audioChunks = [];

    // --- A. VISUAL FEEDBACK (Web Speech API) ---
    // This puts the text into the input box while you speak (Preview)
    if (isWebSpeechSupported) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;

        recognition.onresult = (event) => {
            let interim = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    $('#message-input').val(event.results[i][0].transcript);
                } else {
                    interim += event.results[i][0].transcript;
                    $('#message-input').attr("placeholder", interim);
                }
            }
        };
        recognition.start();
    }

    // --- B. AUDIO CAPTURE (MediaRecorder) ---
    // This records the actual audio to send to Whisper (Backend)
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        
        mediaRecorder.ondataavailable = e => { 
            audioChunks.push(e.data); 
        };
        
        mediaRecorder.onstop = processRecordedAudio;
        mediaRecorder.start();
        
        // UI Updates
        $('#voice-btn').addClass('active');
        $('#voiceIndicator').addClass('active');
        
        // Safety Timeout (Stop after 10s)
        setTimeout(() => { 
            if(micActive) stopMicSession(); 
        }, MAX_MIC_TIME);

    } catch (err) {
        console.error("Mic Error:", err);
        micActive = false;
        alert("Microphone access denied or not available.");
    }
}

function stopMicSession() {
    if (!micActive) return;
    micActive = false;
    
    // Stop Web Speech
    if (recognition) recognition.stop();
    
    // Stop Media Recorder
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
        mediaRecorder.stop();
    }
    
    // Reset UI
    $('#voice-btn').removeClass('active');
    $('#voiceIndicator').removeClass('active');
    $('#message-input').attr("placeholder", "Type or speak...");
}

function toggleMicSession() {
    micActive ? stopMicSession() : startMicSession();
}

function processRecordedAudio() {
    // 1. Check if Web Speech API already captured text
    const capturedText = $('#message-input').val().trim();
    if (capturedText) { 
        // If we have text, just send it directly (Faster)
        sendMessage(); 
        return; 
    }
    
    // 2. If no text captured, send Audio to Whisper (Fallback/Better Accuracy)
    if (audioChunks.length === 0) return;

    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
    const formData = new FormData();
    formData.append('audio_data', audioBlob, 'voice.webm');

    $('#typingIndicator').addClass('active');

    $.ajax({
        url: '/voice',
        type: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function (res) {
            $('#typingIndicator').removeClass('active');
            if (res.status === 'success') {
                addMessage(res.transcription, true);
                addMessage(res.response, false);
                speakText(res.response);
                loadHistoryList();
            }
        },
        error: () => {
            $('#typingIndicator').removeClass('active');
            addMessage("Error processing voice.", false);
        }
    });
}

/* =========================================================
   TEXT-TO-SPEECH (TTS) & UTILS
========================================================= */

function loadVoices() {
    const voices = speechSynthesis.getVoices();
    if (voices.length > 0 && !selectedVoice) {
        selectedVoice = voices[0];
    }
}

function setVoiceGender(gender) {
    const voices = speechSynthesis.getVoices();
    // Try to find a voice that matches the gender, otherwise default to first available
    selectedVoice = voices.find(v => {
        const n = v.name.toLowerCase();
        if (gender === 'male') return n.includes('david') || n.includes('guy') || n.includes('male');
        return n.includes('zira') || n.includes('samantha') || n.includes('female');
    }) || voices[0];
    
    speakText("Voice changed.");
}

function speakText(text) {
    if (!soundEnabled) return;
    
    speechSynthesis.cancel(); // Stop any previous speech
    const utterance = new SpeechSynthesisUtterance(text);
    
    if (selectedVoice) {
        utterance.voice = selectedVoice;
    }
    
    speechSynthesis.speak(utterance);
}

function toggleSound() {
    soundEnabled = !soundEnabled;
    const icon = soundEnabled ? 'fa-volume-high' : 'fa-volume-xmark';
    $('#sound-toggle').html(`<i class="fa-solid ${icon}"></i><span>Sound ${soundEnabled?'ON':'OFF'}</span>`);
    
    if (!soundEnabled) {
        speechSynthesis.cancel();
    }
}

// Helper to prevent XSS (Cross Site Scripting)
function escapeHtml(text) {
    if (!text) return "";
    return text.replace(/[&<>"']/g, m => ({ 
        '&': '&amp;', 
        '<': '&lt;', 
        '>': '&gt;', 
        '"': '&quot;', 
        "'": '&#039;' 
    }[m]));
}