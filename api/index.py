# api/index.py
import os
import json
import logging
import aiofiles
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from upstash_redis import Redis

import api_calls
import utils

# --- Application Setup ---
app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)

# --- Persistent State Management with Vercel Redis ---
redis = Redis(url=os.environ['UPSTASH_REDIS_REST_URL'], token=os.environ['UPSTASH_REDIS_REST_TOKEN'])
SESSION_KEY = "py_bank_converter_session"
MAX_USAGE = 5
MAX_REGISTRATION_ATTEMPTS = 3

async def load_session():
    session_str = await redis.get(SESSION_KEY)
    return json.loads(session_str) if session_str else {"token": None, "usage_count": 0}

async def save_session(session_data):
    await redis.set(SESSION_KEY, json.dumps(session_data))

async def create_new_session():
    logging.info("--- Attempting to create a new session ---")
    for attempt in range(MAX_REGISTRATION_ATTEMPTS):
        logging.info(f"Registration attempt {attempt + 1}/{MAX_REGISTRATION_ATTEMPTS}")
        creds = utils.generate_random_credentials()
        logging.info(f"Generated new credentials for: {creds['email']}")
        try:
            response = await api_calls.register_user(creds['email'], creds['password'], creds['firstName'], creds['lastName'])
            if response.status_code in [200, 201]:
                logging.info("Registration successful.")
                email_id = await api_calls.check_inbox(creds['email'])
                html_content = await api_calls.read_email(email_id)
                if not html_content: raise Exception("Failed to read email content.")
                link = utils.extract_verification_link_from_html(html_content)
                if not link: raise Exception("Failed to extract verification link.")
                await api_calls.verify_email_account(link)
                token = await api_calls.login(creds['email'], creds['password'])
                
                new_session = {"token": token, "usage_count": 0}
                await save_session(new_session)
                logging.info("--- New session created and saved ---")
                return new_session
            else:
                logging.error(f"Registration failed with status {response.status_code}")
        except Exception as e:
            logging.error(f"Exception during session creation attempt {attempt + 1}: {e}")
    raise Exception("Failed to create a new session after multiple attempts.")

async def get_valid_token():
    session = await load_session()
    if not session.get("token") or session.get("usage_count", 0) >= MAX_USAGE:
        logging.info("Token expired or not available. Creating new session.")
        session = await create_new_session()
    return session["token"]

# --- API Endpoints ---
@app.get("/api")
async def root():
    return {"status": "Bank Statement Converter API is fully operational on Vercel with FastAPI"}

@app.post("/api/convert-statement")
async def convert_statement_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF.")

    # Vercel's serverless functions can only write to the /tmp directory
    temp_path = f"/tmp/{file.filename}"
    
    try:
        # Asynchronously save the uploaded file
        async with aiofiles.open(temp_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
        logging.info(f"File '{file.filename}' saved to '{temp_path}'")

        auth_token = await get_valid_token()
        logging.info("Uploading bank statement...")
        upload_uuid = await api_calls.upload_statement(auth_token, temp_path, file.filename)
        logging.info(f"Upload successful. UUID: {upload_uuid}")

        csv_data = await api_calls.poll_and_convert_statement(auth_token, upload_uuid)
        
        session = await load_session()
        session["usage_count"] = session.get("usage_count", 0) + 1
        await save_session(session)
        logging.info(f"Token usage updated to: {session['usage_count']}/{MAX_USAGE}")
        
        headers = {'Content-Disposition': f'attachment; filename="converted_{file.filename}.csv"'}
        return Response(content=csv_data, media_type='text/csv', headers=headers)

    except Exception as e:
        logging.error(f"An error occurred in the main endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal server error occurred: {e}")
    finally:
        # Clean up the temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)
            logging.info(f"Cleaned up temporary file: {temp_path}")
