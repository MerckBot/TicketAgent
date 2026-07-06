"""
token_manager.py (v1.2)
StubHub OAuth 2.0 Client Credentials token lifecycle.

v1.2 changes:
- Token cached in memory for the run instead of /tmp (GitHub runners are
  ephemeral, so the file cache never survived anyway).
- stubhub_creds_present() lets fetchers skip cleanly before creds exist.
- NOTE: endpoint/scopes are from the older StubHub developer program —
  verify against whatever their API team sends back with your credentials.
"""

import os
import time
import base64

import requests

TOKEN_URL = "https://account.stubhub.com/oauth2/token"

_cache = {"access_token": None, "expires_at": 0}


def stubhub_creds_present():
    cid = os.environ.get("STUBHUB_CLIENT_ID", "")
    secret = os.environ.get("STUBHUB_CLIENT_SECRET", "")
    return (bool(cid) and bool(secret)
            and not cid.startswith("PLACEHOLDER")
            and not secret.startswith("PLACEHOLDER"))


def get_stubhub_token():
    if _cache["access_token"] and time.time() < _cache["expires_at"]:
        return _cache["access_token"]

    client_id = os.environ["STUBHUB_CLIENT_ID"]
    client_secret = os.environ["STUBHUB_CLIENT_SECRET"]
    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode()).decode()

    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    _cache["access_token"] = data["access_token"]
    _cache["expires_at"] = time.time() + data.get("expires_in", 3600) - 300
    return _cache["access_token"]
