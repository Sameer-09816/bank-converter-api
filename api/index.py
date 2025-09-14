# api/index.py
import os
import json
import logging
import traceback
import aiofiles
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as redis

# Import from root
import api_calls
import utils

# --- Application Lifespan for Graceful Startup/Shutdown ---
# This is a modern FastAPI feature to manage resources like database connections.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Code to run on startup ---
    logging.info("Application startup...")
    REDIS_CONNECTION_URL = os.environ.get('REDIS_URL')
    if not REDIS_CONNECTION_URL:
        logging.error("FATAL: REDIS_URL environment variable not found.")
        app.state.redis_client = None
    else:
        try:
            # Create the client and attach it to the app's state
            app.state.redis_client = redis.from_url(REDIS_CONNECTION_URL, decode_responses=True)
            # Test the connection
            await app.state.redis_client.ping()
            logging.info("Successfully connected to Redis.")
        except Exception as e:
            logging.error(f"FATAL: Could not connect to Redis during startup. Error: {e}")
            app.state.redis_client = None
    yield
    # --- Code to run on shutdown ---
    logging.info("Application shutdown...")
    if app.state.redis_client:
        await app.state.redis_client.close()
        logging.info("Redis connection closed.")


# --- Application Setup with Lifespan ---
app = FastAPI(
    title="Bank Statement Converter API",
    description="An automated API to convert bank statement PDFs to CSV format.",
    version="1.2.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan # Attach the lifespan event handler
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
logging.basicConfig(level=logging.INFO)

SESSION_KEY = "py_bank_converter_session_final"
MAX_USAGE = 5
MAX_REGISTRATION_ATTEMPTS = 3

# --- Global Exception Handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # ... (unchanged)
    error_traceback = traceback.format_exc()
    logging.error(f"Unhandled exception for request {request.url.path}: {exc}")
    logging.error(error_traceback)
    return JSONResponse(status_code=500, content={"error": "Internal Server Error", "message": "An unexpected error occurred."})

# --- State Management (Now uses app.state.redis_client) ---
async def check_redis_connection(request: Request):
    if request.app.state.redis_client is None:
        raise HTTPException(status_code=503, detail="Service Unavailable: Redis database is not configured or connection failed.")
    return request.app.state.redis_client

async def load_session(redis_client):
    session_str = await redis_client.get(SESSION_KEY)
    return json.loads(session_str) if session_str else {"token": None, "usage_count": 0}

async def save_session(redis_client, session_data):
    await redis_client.set(SESSION_KEY, json.dumps(session_data))

async def create_new_session():
    # ... (unchanged)
    logging.info("--- Attempting to create a new session ---")
    for attempt in range(MAX_REGISTRATION_ATTEMPTS):
        logging.info(f"Registration attempt {attempt + 1}/{MAX_REGISTRATION_ATTEMPTS}")
        creds = utils.generate_random_credentials()
        try:
            response = await api_calls.register_user(creds['email'], creds['password'], creds['firstName'], creds['lastName'])
            if response.status_code in [200, 201]:
                email_id = await api_calls.check_inbox(creds['email'])
                html_content = await api_calls.read_email(email_id)
                if not html_content: raise Exception("Failed to read email content.")
                link = utils.extract_verification_link_from_html(html_content)
                if not link: raise Exception("Failed to extract verification link.")
                await api_calls.verify_email_account(link)
                token = await api_calls.login(creds['email'], creds['password'])
                return {"token": token, "usage_count": 0}
            else:
                logging.error(f"Registration failed with status {response.status_code}")
        except Exception as e:
            logging.error(f"Exception during session creation: {e}", exc_info=True)
    raise Exception("Failed to create a new session after multiple attempts.")


async def get_valid_token(request: Request):
    redis_client = await check_redis_connection(request)
    session = await load_session(redis_client)
    if not session.get("token") or session.get("usage_count", 0) >= MAX_USAGE:
        logging.info("Token expired or not available. Creating new session.")
        session = await create_new_session()
        await save_session(redis_client, session) # Save the new session immediately
    return session["token"]

# --- API Endpoints ---
@app.get("/api", tags=["Status"])
async def root():
    return {"status": "API is operational"}

@app.post("/api/convert-statement", tags=["Conversion"])
async def convert_statement_endpoint(request: Request, file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF.")
    
    temp_path = f"/tmp/{file.filename}"
    try:
        # Optimized chunk-based file writing to reduce memory usage
        async with aiofiles.open(temp_path, 'wb') as out_file:
            while content := await file.read(1024 * 1024): # Read in 1MB chunks
                await out_file.write(content)
        logging.info(f"File '{file.filename}' saved to '{temp_path}'")

        auth_token = await get_valid_token(request)
        
        logging.info("Uploading bank statement...")
        upload_uuid = await api_calls.upload_statement(auth_token, temp_path, file.filename)
        logging.info(f"Upload successful. UUID: {upload_uuid}")

        csv_data = await api_calls.poll_and_convert_statement(auth_token, upload_uuid)
        
        redis_client = await check_redis_connection(request)
        session = await load_session(redis_client)
        session["usage_count"] = session.get("usage_count", 0) + 1
        await save_session(redis_client, session)
        logging.info(f"Token usage updated to: {session['usage_count']}/{MAX_USAGE}")
        
        headers = {'Content-Disposition': f'attachment; filename="converted_{file.filename}.csv"'}
        return Response(content=csv_data, media_type='text/csv', headers=headers)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
