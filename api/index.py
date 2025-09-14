# api/index.py
import os
import json
import logging
import traceback
import aiofiles
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis # **FIX**: Import the standard asyncio redis client

# Vercel's build environment places root files where they can be imported directly.
import api_calls
import utils

# --- Application Setup with Documentation ---
app = FastAPI(
    title="Bank Statement Converter API",
    description="An unofficial API that automates the process of converting bank statement PDFs to CSV format. It manages accounts and sessions automatically for continuous use.",
    version="1.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)
logging.basicConfig(level=logging.INFO)

# --- Robust Initialization with Environment Variable Checks ---
REDIS_CONNECTION_URL = os.environ.get('REDIS_URL')

if not REDIS_CONNECTION_URL:
    logging.error("FATAL ERROR: REDIS_URL environment variable is not set.")
    redis_client = None
else:
    # **FIX**: Initialize the standard redis-py async client from the URL
    try:
        redis_client = redis.from_url(REDIS_CONNECTION_URL, decode_responses=True)
    except Exception as e:
        logging.error(f"FATAL ERROR: Could not connect to Redis. Please check the REDIS_URL. Error: {e}")
        redis_client = None


SESSION_KEY = "py_bank_converter_session_final"
MAX_USAGE = 5
MAX_REGISTRATION_ATTEMPTS = 3

# --- Global Exception Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_traceback = traceback.format_exc()
    logging.error(f"Unhandled exception for request {request.url.path}: {exc}")
    logging.error(error_traceback)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred. The server logs have more details.",
            "exception_type": type(exc).__name__
        },
    )

async def check_redis_connection():
    """Helper function to check for Redis before any operation."""
    if redis_client is None:
        raise HTTPException(
            status_code=503, 
            detail="Service Unavailable: Redis database is not configured or connection failed."
        )

# --- State Management (Now using redis-py syntax) ---
async def load_session():
    await check_redis_connection()
    session_str = await redis_client.get(SESSION_KEY) # **FIX**: Use redis_client
    return json.loads(session_str) if session_str else {"token": None, "usage_count": 0}

async def save_session(session_data):
    await check_redis_connection()
    await redis_client.set(SESSION_KEY, json.dumps(session_data)) # **FIX**: Use redis_client

# ... (The rest of the functions like create_new_session and get_valid_token are unchanged internally)
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
            logging.error(f"Exception during session creation attempt {attempt + 1}: {e}", exc_info=True)
    raise Exception("Failed to create a new session after multiple attempts.")
async def get_valid_token():
    session = await load_session()
    if not session.get("token") or session.get("usage_count", 0) >= MAX_USAGE:
        logging.info("Token expired or not available. Creating new session.")
        session = await create_new_session()
    return session["token"]

# --- API Endpoints with Documentation ---
@app.get("/api", tags=["Status"], summary="Check API Health")
async def root():
    return {"status": "Bank Statement Converter API is fully operational"}

@app.post("/api/convert-statement", tags=["Conversion"], summary="Convert a Bank Statement PDF to CSV")
async def convert_statement_endpoint(file: UploadFile = File(..., description="The bank statement PDF file to be converted.")):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF.")
    temp_path = f"/tmp/{file.filename}"
    try:
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
        session["usage_count"] = se
