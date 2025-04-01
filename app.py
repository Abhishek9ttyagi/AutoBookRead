from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pyttsx3
from PyPDF2 import PdfReader
import os
import uuid # For unique filenames
import time # For potential cleanup later
from dotenv import load_dotenv # For API Key security
import google.generativeai as genai # Import Google AI library

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# Configure CORS more specifically for production if needed
CORS(app)

# --- Configuration ---
UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'audio_output'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

# Configure Google AI
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
if not GOOGLE_API_KEY:
    print("Warning: GOOGLE_API_KEY environment variable not set.")
    # Potentially raise an error or handle gracefully
else:
    genai.configure(api_key=GOOGLE_API_KEY)
    ai_model = genai.GenerativeModel('gemini-1.5-flash') # Use a valid model name

# --- Helper Functions ---
def extract_text_from_pdf(pdf_path, start_page, end_page):
    """Extracts text from a specific page range in a PDF."""
    try:
        reader = PdfReader(pdf_path)
        num_pages_actual = len(reader.pages)

        # Validate page numbers
        start_page = max(1, start_page)
        end_page = min(num_pages_actual, end_page)
        if start_page > end_page:
            return "" # Or raise an error

        text = ""
        for page_num in range(start_page - 1, end_page):
            if page_num < num_pages_actual:
                page = reader.pages[page_num]
                text += page.extract_text() or "" # Add 'or ""' for robustness
        return text
    except Exception as e:
        print(f"Error extracting text from PDF {pdf_path}: {e}")
        raise # Re-raise the exception to be caught by the route handler

def generate_unique_filename(original_filename):
    """Generates a unique filename to prevent overwrites."""
    ext = os.path.splitext(original_filename)[1]
    unique_name = f"{uuid.uuid4()}{ext}"
    return unique_name

# --- API Routes ---
@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # Basic security check for extension (can be improved)
    allowed_extensions = {'.pdf'}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        return jsonify({'error': 'Invalid file type, only PDF allowed'}), 400

    if file:
        try:
            # Generate unique filename before saving
            unique_filename = generate_unique_filename(file.filename)
            pdf_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            file.save(pdf_path)

            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            # Return the unique filename used on the server
            return jsonify({'server_filename': unique_filename, 'num_pages': num_pages})
        except Exception as e:
            print(f"Error uploading/reading file {file.filename}: {e}")
            return jsonify({'error': 'Failed to process uploaded file'}), 500
    else:
         return jsonify({'error': 'File object is invalid'}), 400


@app.route('/text', methods=['POST'])
def get_text():
    try:
        data = request.json
        server_filename = data.get('server_filename')
        start_page = int(data.get('start_page', 1))
        end_page = int(data.get('end_page', 1))

        if not server_filename:
            return jsonify({'error': 'Missing server_filename'}), 400

        pdf_path = os.path.join(UPLOAD_FOLDER, server_filename)
        if not os.path.exists(pdf_path):
             return jsonify({'error': 'PDF file not found on server'}), 404

        text = extract_text_from_pdf(pdf_path, start_page, end_page)
        return jsonify({'text': text})
    except FileNotFoundError:
         return jsonify({'error': 'PDF file not found on server'}), 404
    except ValueError:
        return jsonify({'error': 'Invalid page numbers provided'}), 400
    except Exception as e:
        print(f"Error in /text endpoint: {e}")
        return jsonify({'error': 'Failed to extract text'}), 500

@app.route('/summarize', methods=['POST'])
def summarize_text():
    if not GOOGLE_API_KEY:
         return jsonify({'error': 'AI Service not configured on server'}), 500
    try:
        data = request.json
        text = data.get('text')
        if not text:
            return jsonify({'error': 'No text provided for summarization'}), 400

        # --- Call Google Generative AI ---
        prompt = f"""Summarize the following text point-wise in Markdown format.
        Each main point should start with '* '.
        Ensure the summary is concise, well-structured, and covers the key information.
        Do not include any introductory or concluding phrases like "Here is the summary:".

        Text to summarize:
        ---
        {text}
        ---
        Summary:
        """

        response = ai_model.generate_content(prompt)
        # print("AI Raw Response:", response.text) # Debugging
        summary = response.text.strip() # Get the summarized text

        return jsonify({'summary': summary})

    except Exception as e:
        print(f"Error during summarization: {e}")
        # Handle potential API errors more specifically if needed
        # print("Google AI Response details:", getattr(e, 'response', 'No response object'))
        return jsonify({'error': f'Failed to generate summary: {e}'}), 500

@app.route('/tts', methods=['POST'])
def text_to_speech():
    try:
        data = request.json
        text = data.get('text')
        if not text:
            return jsonify({'error': 'No text provided for TTS'}), 400

        # Generate unique filename for the audio output
        audio_filename = f"{uuid.uuid4()}.mp3"
        audio_filepath = os.path.join(AUDIO_FOLDER, audio_filename)

        # Initialize TTS engine
        engine = pyttsx3.init()
        # Optional: Configure voice, rate, volume
        # voices = engine.getProperty('voices')
        # engine.setProperty('voice', voices[1].id) # Example: Set a different voice
        # engine.setProperty('rate', 150)

        # Save to file instead of blocking with engine.say()
        engine.save_to_file(text, audio_filepath)
        engine.runAndWait() # Process the command queue (saving)
        engine.stop() # Stop the engine instance cleanly

        # Check if file was created (basic check)
        if not os.path.exists(audio_filepath) or os.path.getsize(audio_filepath) == 0:
             print(f"Warning: TTS file might be empty or not created: {audio_filepath}")
             # Fallback or error if needed

        # Return the URL path to the generated audio file
        audio_url = f"/audio/{audio_filename}"
        return jsonify({'status': 'completed', 'audio_url': audio_url})

    except Exception as e:
        print(f"Error during Text-to-Speech: {e}")
        return jsonify({'error': 'Failed to generate audio'}), 500

@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """Serves the generated audio files."""
    try:
        # Security: Ensure filename is safe (though UUID helps)
        # Add more path validation/sanitization if needed
        return send_from_directory(AUDIO_FOLDER, filename, as_attachment=False)
    except FileNotFoundError:
        return jsonify({"error": "Audio file not found"}), 404

# --- Cleanup (Optional but Recommended) ---
# You might add a background task or periodic job to delete old files
# from UPLOAD_FOLDER and AUDIO_FOLDER, especially for public deployments.

# --- Running the App ---
if __name__ == '__main__':
    # Use debug=False for production
    # Use a proper WSGI server like Gunicorn or Waitress for production
    app.run(debug=True, port=5000)