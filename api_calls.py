# api_calls.py
import requests
import time
import logging

# --- API Endpoints ---
BSC_API_BASE = "https://api2.bankstatementconverter.com/api/v1"
TEMP_MAIL_API_BASE = "https://api.barid.site"

# Set a reasonable timeout for all external requests
REQUEST_TIMEOUT = 30 

def register_user(email, password, first_name, last_name):
    """Registers a new user on BankStatementConverter."""
    url = f"{BSC_API_BASE}/register"
    payload = {
        "email": email,
        "password": password,
        "firstName": first_name,
        "lastName": last_name,
        "referredBy": ""
    }
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status() # Will raise an exception for 4xx/5xx errors
    return response.json()

def check_inbox(email):
    """Polls the temporary email inbox until the verification email arrives."""
    url = f"{TEMP_MAIL_API_BASE}/emails/{email}"
    max_retries = 10
    retry_delay = 5  # seconds
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            if data.get("success") and data.get("result"):
                for email_item in data["result"]:
                    if "verify email" in email_item.get("subject", "").lower():
                        logging.info(f"Verification email found for {email}.")
                        return email_item["id"]
        except requests.RequestException as e:
            logging.warning(f"Error checking inbox (attempt {attempt+1}/{max_retries}): {e}")
        
        logging.info(f"Email not found yet for {email}. Retrying in {retry_delay}s...")
        time.sleep(retry_delay)
    
    raise Exception("Verification email did not arrive in time.")

def read_email(email_id):
    """Reads the content of a specific email from the temporary inbox."""
    url = f"{TEMP_MAIL_API_BASE}/inbox/{email_id}"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if data.get("success") and data.get("result"):
        return data["result"]["html_content"]
    raise Exception("Failed to read email content.")

def verify_email_account(verification_link):
    """'Clicks' the verification link by making a GET request to it."""
    response = requests.get(verification_link, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    logging.info(f"Email verification link accessed successfully. Status: {response.status_code}")
    return True

def login(email, password):
    """Logs the user in to get an authentication token."""
    url = f"{BSC_API_BASE}/login"
    payload = {"email": email, "password": password}
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if "token" in data:
        return data["token"]
    raise Exception("Login failed: token not found in response.")

def upload_statement(auth_token, file_path, filename):
    """Uploads the bank statement PDF file."""
    url = f"{BSC_API_BASE}/BankStatement"
    headers = {"Authorization": auth_token}
    with open(file_path, 'rb') as f:
        files = {'files': (filename, f, 'application/pdf')}
        response = requests.post(url, headers=headers, files=files, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if data and isinstance(data, list) and "uuid" in data[0]:
        return data[0]["uuid"]
    raise Exception("Upload failed: UUID not found in response.")

def convert_statement(auth_token, uuid):
    """Requests the conversion of the uploaded file to CSV format."""
    url = f"{BSC_API_BASE}/BankStatement/convert?format=CSV"
    headers = {
        "Authorization": auth_token,
        "Content-Type": "text/plain;charset=UTF-8" # As per user's provided headers
    }
    # The payload is a plain text string of a JSON array
    payload = f'["{uuid}"]'
    response = requests.post(url, headers=headers, data=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text # The response is raw CSV text