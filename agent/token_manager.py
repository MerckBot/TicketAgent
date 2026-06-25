"""
token_manager.py
Handles StubHub OAuth 2.0 Client Credentials token lifecycle.
"""

import os
import time
import base64
import json
import requests

TOKEN_CACHE_FILE = "/tmp/stubhub_token.json"
TOKEN_URL = "https://account.stubhub.com/oauth2/token"


def _load_cached_token():
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE) as f:
            return json.load(f)
    return None


def _save_token(token_data):
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump(token_data, f)


def _fetch_new_token(client_id, client_secret):
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials", "scope": "read:events read:listings"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    token_data = {
        "access_token": data["access_token"],
        "expires_at": time.time() + data.get("expires_in", 3600) - 300,  # 5-min buffer
    }
    _save_token(token_data)
    return token_data["access_token"]


def get_stubhub_token():
    client_id = os.environ.get("STUBHUB_CLIENT_ID", "PLACEHOLDER_CLIENT_ID")
    client_secret = os.environ.get("STUBHUB_CLIENT_SECRET", "PLACEHOLDER_CLIENT_SECRET")

    cached = _load_cached_token()
    if cached and time.time() < cached.get("expires_at", 0):
        return cached["access_token"]

    return _fetch_new_token(client_id, client_secret)
