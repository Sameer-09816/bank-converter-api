# utils.py
import random
import string
import time
import asyncio
from bs4 import BeautifulSoup

def generate_random_credentials(): # ... (code is unchanged)
    domains = ["vwh.sh", "iusearch.lol", "barid.site", "z44d.pro", "wael.fun", "kuruptd.ink"]
    random_part = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    timestamp_part = int(time.time() * 1000)
    username = f"{random_part}{timestamp_part}"
    email = f"{username}@{random.choice(domains)}"
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    first_name = ''.join(random.choices(string.ascii_lowercase, k=6))
    last_name = ''.join(random.choices(string.ascii_lowercase, k=6))
    return {"email": email, "password": password, "firstName": first_name, "lastName": last_name}

def extract_verification_link_from_html(html_content: str): # ... (code is unchanged)
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        verify_link_tag = soup.find('a', string=lambda text: text and 'verify my email' in text.lower())
        if verify_link_tag and 'href' in verify_link_tag.attrs:
            return verify_link_tag['href']
    except Exception:
        return None
    return None

async def async_sleep(seconds: int):
    await asyncio.sleep(seconds)
