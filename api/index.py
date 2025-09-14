import os
import random
import string
import re
import json
import asyncio
from typing import Optional

import httpx
import redis
from bs4 import BeautifulSoup
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse

# --- Configuration ---
BANK_API_BASE = "https://api2.bankstatementconverter.com/api/v1"
TEMP_MAIL_API_BASE = "https://api.barid.site"
TEMP_MAIL_DOMAINS = [
    "barid.site", "vwh.sh", "iusearch.lol", "lifetalk.us",
    "z44d.pro", "wael.fun", "tawbah.site", "kuruptd.ink", "oxno.space"
]

# --- State Management Class ---
class AccountManager:
    """
    Manages the account lifecycle using Redis for persistent state.
    """
    def __init__(self):
        # WARNING: Hardcoding secrets is a security risk. Use environment variables in production.
        redis_url = "rediss://default:51SWVc4IIcxy9obgiDUL4wy3jlUR5mgH@redis-16077.crce214.us-east-1-3.ec2.redns.redis-cloud.com:16077"

        try:
            self.redis_client = redis.from_url(redis_url, ssl_cert_reqs=None)
            self.redis_client.ping()
            print("Successfully connected to Redis Cloud (SSL verification disabled).")
        except Exception as e:
            print(f"CRITICAL: Could not connect to Redis. Error: {e}")
            self.redis_client = None

    def _generate_credentials(self):
        """Generates random credentials."""
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        domain = random.choice(TEMP_MAIL_DOMAINS)
        email = f"{username}@{domain}"
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        return email, password

    async def _get_verification_link(self, client: httpx.AsyncClient, email: str) -> Optional[str]:
        """Polls the inbox, respecting serverless timeout limits."""
        for _ in range(3):
            print(f"Checking inbox for {email}...")
            try:
                inbox_res = await client.get(f"{TEMP_MAIL_API_BASE}/emails/{email}", timeout=5.0)
                inbox_res.raise_for_status()
                inbox_data = inbox_res.json()
                if inbox_data.get("success") and inbox_data.get("result"):
                    email_id = inbox_data["result"][0].get("id")
                    content_res = await client.get(f"{TEMP_MAIL_API_BASE}/inbox/{email_id}", timeout=5.0)
                    html_content = content_res.json()["result"]["html_content"]
                    soup = BeautifulSoup(html_content, 'html.parser')
                    link_tag = soup.find('a', string=re.compile(r'\s*Verify my email\s*'))
                    if link_tag and 'href' in link_tag.attrs:
                        print("Verification link found.")
                        return link_tag['href']
            except Exception as e:
                print(f"Warning: Issue while polling email: {e}")
            await asyncio.sleep(2)
        print("Verification link not found in time.")
        return None

    async def create_new_account(self):
        """Creates a new account and saves its state to Redis."""
        if not self.redis_client:
            raise HTTPException(status_code=503, detail="State management service (Redis) is not available.")

        print("Creating a new account and saving state to Redis...")
        email, password = self._generate_credentials()
        credentials = {"email": email, "firstName": "Test", "lastName": "User", "password": password, "referredBy": ""}

        async with httpx.AsyncClient(timeout=9.0) as client:
            await client.post(f"{BANK_API_BASE}/register", json=credentials)
            verification_link = await self._get_verification_link(client, email)
            if not verification_link:
                raise HTTPException(status_code=504, detail="Could not retrieve verification email within the time limit.")
            
            await client.get(verification_link, follow_redirects=True)
            
            login_res = await client.post(f"{BANK_API_BASE}/login", json={"email": email, "password": password})
            login_res.raise_for_status()
            token = login_res.json()["token"]

            self.redis_client.set("auth_token", token)
            self.redis_client.set("credits", 5)
            print("New account state saved successfully to Redis.")
            return token

    async def get_valid_token(self) -> str:
        """Retrieves a valid token from Redis, creating a new account if necessary."""
        credits_bytes = self.redis_client.get("credits")
        credits = int(credits_bytes) if credits_bytes else 0

        if credits <= 0:
            print("No credits in Redis. Triggering new account creation.")
            return await self.create_new_account()
        
        token_bytes = self.redis_client.get("auth_token")
        if not token_bytes:
            print("No token in Redis. Triggering new account creation.")
            return await self.create_new_account()
            
        print(f"Retrieved valid token from Redis. Credits remaining: {credits}")
        return token_bytes.decode('utf-8')

    def use_credit(self):
        """Decrements the credit count in Redis atomically."""
        if self.redis_client:
            new_credit_count = self.redis_client.decr("credits")
            print(f"Credit used. Remaining credits in Redis: {new_credit_count}")

# --- FastAPI Application ---

## FIX: Re-enabled the documentation by removing `docs_url=None, redoc_url=None`.
app = FastAPI(
    title="Vercel-Hosted Bank Statement Converter API",
    description="An efficient, serverless API wrapper using Redis for state management. Interactive docs are available at /docs.",
    version="3.4.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

account_manager = AccountManager()

@app.get("/", summary="Health Check")
@app.get("/api", summary="Health Check")
@app.get("/api/index", summary="Health Check")
def read_root():
    return {"status": "API is running"}

@app.post("/api/convert-statement", summary="Convert a Bank Statement PDF to CSV")
async def convert_bank_statement(file: UploadFile = File(..., description="The bank statement PDF file to be converted.")):
    if not account_manager.redis_client:
        raise HTTPException(status_code=503, detail="State management service is currently unavailable. Please try again later.")

    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF.")

    try:
        token = await account_manager.get_valid_token()
        headers = {"Authorization": token}
        
        async with httpx.AsyncClient(timeout=9.0) as client:
            files = {'files': (file.filename, file.file, file.content_type)}
            upload_res = await client.post(f"{BANK_API_BASE}/BankStatement", headers=headers, files=files)
            upload_res.raise_for_status()
            file_uuid = upload_res.json()[0]["uuid"]
            
            convert_headers = headers.copy()
            convert_headers['Content-Type'] = 'text/plain;charset=UTF-8'
            convert_res = await client.post(
                f"{BANK_API_BASE}/BankStatement/convert?format=CSV", 
                headers=convert_headers, content=json.dumps([file_uuid])
            )
            convert_res.raise_for_status()
            
            account_manager.use_credit()
            return PlainTextResponse(content=convert_res.text)

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            print("Received 401 Unauthorized. Invalidating state in Redis.")
            if account_manager.redis_client:
                account_manager.redis_client.set("credits", 0)
        raise HTTPException(status_code=e.response.status_code, detail=f"Error from backend: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")
