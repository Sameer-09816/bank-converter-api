# api_calls.py
import logging
import httpx
from utils import async_sleep

# ... (The full, correct code from the previous response is unchanged)
BSC_API_BASE = "https://api2.bankstatementconverter.com/api/v1"
TEMP_MAIL_API_BASE = "https://api.barid.site"
REQUEST_TIMEOUT = 60.0
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
}
async def poll_and_convert_statement(auth_token: str, uuid: str): # ... (code is unchanged)
    url = f"{BSC_API_BASE}/BankStatement/convert?format=CSV"
    headers = {**COMMON_HEADERS, "Authorization": auth_token, "Content-Type": "text/plain;charset=UTF-8", "Accept": "text/csv,*/*;q=0.8"}
    payload = f'["{uuid}"]'
    max_wait_time, poll_interval = 90, 3
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for _ in range(max_wait_time // poll_interval):
            try:
                response = await client.post(url, headers=headers, content=payload)
                if response.status_code == 200:
                    logging.info(f"Conversion successful for UUID {uuid}.")
                    return response.text
                elif response.status_code == 400:
                    logging.info(f"File {uuid} not ready (400). Retrying...")
                    await async_sleep(poll_interval)
                else:
                    response.raise_for_status()
            except httpx.RequestError as e:
                logging.error(f"Network error polling conversion for {uuid}: {e}")
                await async_sleep(poll_interval)
    raise Exception(f"Conversion timed out for file {uuid}.")
# ... (rest of the functions in api_calls.py are also unchanged)
async def register_user(email, password, first_name, last_name):
    url = f"{BSC_API_BASE}/register"
    payload = {"email": email, "password": password, "firstName": first_name, "lastName": last_name, "referredBy": ""}
    headers = {**COMMON_HEADERS, 'Accept': 'application/json'}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response
async def check_inbox(email: str):
    url = f"{TEMP_MAIL_API_BASE}/emails/{email}"
    headers = {**COMMON_HEADERS, 'Accept': 'application/json'}
    max_retries, retry_delay = 15, 5
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for i in range(max_retries):
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                if data.get("success") and data.get("result"):
                    for item in data["result"]:
                        if "verify email" in item.get("subject", "").lower():
                            logging.info("Verification email found.")
                            return item["id"]
            except httpx.RequestError as e:
                logging.warning(f"Error checking inbox (attempt {i+1}): {e}")
            logging.info(f"Email not found. Retrying...")
            await async_sleep(retry_delay)
    raise Exception("Verification email did not arrive in time.")
async def read_email(email_id: str):
    url = f"{TEMP_MAIL_API_BASE}/inbox/{email_id}"
    headers = {**COMMON_HEADERS, 'Accept': 'application/json'}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get("success"):
            return data.get("result", {}).get("html_content")
    raise Exception("Failed to read email content.")
async def verify_email_account(verification_link: str):
    headers = {**COMMON_HEADERS, 'Accept': 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8'}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(verification_link, headers=headers)
        response.raise_for_status()
        logging.info(f"Verification link accessed. Final URL: {response.url}, Status: {response.status_code}")
async def login(email, password):
    url = f"{BSC_API_BASE}/login"
    payload = {"email": email, "password": password}
    headers = {**COMMON_HEADERS, 'Accept': 'application/json'}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if "token" in data:
            return data["token"]
    raise Exception("Login failed: token not found.")
async def upload_statement(auth_token, file_path, filename):
    url = f"{BSC_API_BASE}/BankStatement"
    headers = {**COMMON_HEADERS, "Authorization": auth_token, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        with open(file_path, "rb") as f:
            files = {"files": (filename, f, "application/pdf")}
            response = await client.post(url, headers=headers, files=files)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0 and "uuid" in data[0]:
                return data[0]["uuid"]
    raise Exception(f"Upload failed: UUID not found. Response: {data}")
