# main.py
import os
import sys
import json
import logging
import tempfile
import traceback
import threading
import shutil
from fastapi import FastAPI, File, UploadFile, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

# Ensure other modules can be imported
sys.path.insert(0, os.path.dirname(__file__))
import api_calls
import utils

# --- Application Setup ---
app = FastAPI(
    title="Bank Statement Converter API",
    description="An API to convert PDF bank statements to CSV format.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Persistent State Management ---
# IMPORTANT: This file-based state with a threading.Lock is NOT process-safe.
# You MUST run Gunicorn with a single worker (`--workers 1`) to avoid race conditions.
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'session.json')
STATE_LOCK = threading.Lock()
MAX_USAGE = 5
MAX_REGISTRATION_ATTEMPTS = 5


def _load_session():
    if not os.path.exists(SESSION_FILE):
        return {"token": None, "usage_count": 0}
    try:
        with open(SESSION_FILE, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {"token": None, "usage_count": 0}

def _save_session(session_data):
    with open(SESSION_FILE, 'w') as f:
        json.dump(session_data, f)

def _create_new_session():
    logging.info("--- Attempting to create a new session ---")
    for attempt in range(MAX_REGISTRATION_ATTEMPTS):
        logging.info(f"Registration attempt {attempt + 1}/{MAX_REGISTRATION_ATTEMPTS}")
        credentials = utils.generate_random_credentials()
        logging.info(f"Generated new credentials for: {credentials['email']}")
        try:
            # Note: api_calls are synchronous, FastAPI runs them in a thread pool
            api_calls.register_user(credentials['email'], credentials['password'], credentials['firstName'], credentials['lastName'])
            logging.info("Registration successful.")
            email_id = api_calls.check_inbox(credentials['email'])
            html_content = api_calls.read_email(email_id)
            if not html_content: raise Exception("Failed to read email content, cannot verify.")
            verification_link = utils.extract_verification_link_from_html(html_content)
            if not verification_link: raise Exception("Failed to extract verification link from email.")
            api_calls.verify_email_account(verification_link)
            token = api_calls.login(credentials['email'], credentials['password'])
            new_session = {"token": token, "usage_count": 0}
            _save_session(new_session)
            logging.info("--- New session created and saved successfully ---")
            return new_session
        except Exception as e:
            logging.error(f"Exception during session creation attempt {attempt + 1}: {e}")
            logging.error(traceback.format_exc())
    raise Exception("Failed to create a new session after multiple attempts.")

def get_valid_token():
    with STATE_LOCK:
        session = _load_session()
        if not session.get("token") or session.get("usage_count", 0) >= MAX_USAGE:
            session = _create_new_session()
        return session["token"]

# --- API Endpoints ---
@app.get("/")
def index():
    return {"status": "Bank Statement Converter API is running"}

@app.post('/api/convert-statement')
async def convert_statement_endpoint(file: UploadFile = File(...)):
    if not file or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="A valid PDF file is required.")

    # Use a temporary file to save the uploaded content
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, 'wb') as tmp:
            shutil.copyfileobj(file.file, tmp)
        
        logging.info(f"File '{file.filename}' saved to '{temp_path}'")
        
        auth_token = get_valid_token() # This is a synchronous call
        
        logging.info("Uploading bank statement...")
        upload_uuid = api_calls.upload_statement(auth_token, temp_path, file.filename)
        logging.info(f"Upload successful. UUID: {upload_uuid}")
        
        csv_data = api_calls.poll_and_convert_statement(auth_token, upload_uuid)

        with STATE_LOCK:
            session = _load_session()
            session["usage_count"] = session.get("usage_count", 0) + 1
            _save_session(session)
            logging.info(f"Token usage updated to: {session['usage_count']}/{MAX_USAGE}")
            
        csv_filename = f"converted_{os.path.splitext(file.filename)[0]}.csv"
        headers = {"Content-Disposition": f"attachment; filename={csv_filename}"}
        return Response(content=csv_data, media_type="text/csv", headers=headers)

    except Exception as e:
        logging.error(f"An error occurred in the main endpoint: {str(e)}")
        logging.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")
    finally:
        # Clean up the temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
        # It's good practice to close the file object of the UploadFile
        await file.close()