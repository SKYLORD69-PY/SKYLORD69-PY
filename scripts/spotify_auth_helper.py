#!/usr/bin/env python3
"""
spotify_auth_helper.py
-------------------------
Run this ONCE, locally, on your own machine (never in GitHub Actions).
It walks you through Spotify's OAuth Authorization Code flow and
prints the one thing the workflow actually needs long-term: a
refresh token. After this, the helper is never needed again unless
you revoke access.

Usage:
    pip install -r requirements.txt   # only needs stdlib, but keeps parity
    export SPOTIFY_CLIENT_ID=...
    export SPOTIFY_CLIENT_SECRET=...
    python scripts/spotify_auth_helper.py

Then paste the printed URL into a browser, approve access, and this
script will catch the redirect automatically and print your
SPOTIFY_REFRESH_TOKEN.
"""

import base64
import http.server
import json
import os
import sys
import urllib.parse
import urllib.request
import webbrowser

# Read credentials from the environment so the script never ships secrets
# in source control.
# export SPOTIFY_CLIENT_ID=...
# export SPOTIFY_CLIENT_SECRET=...

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-currently-playing user-read-recently-played"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

_captured_code = {}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _captured_code["code"] = params["code"][0]
            body = b"<h2>Got it! You can close this tab and go back to your terminal.</h2>"
        else:
            body = b"<h2>No authorization code found in the redirect. Check the terminal.</h2>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # keep the terminal output clean


def main():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your shell first.",
              file=sys.stderr)
        sys.exit(1)

    query = urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "show_dialog": "true",
    })
    auth_url = f"{AUTH_URL}?{query}"

    print("Make sure this exact URI is added under 'Redirect URIs' in your Spotify")
    print(f"app settings first: {REDIRECT_URI}\n")
    print("Opening your browser. If it doesn't open, visit this URL manually:\n")
    print(auth_url, "\n")
    try:
        webbrowser.open(auth_url)
    except Exception:  # noqa: BLE001
        pass

    server = http.server.HTTPServer(("127.0.0.1", 8888), CallbackHandler)
    print("Waiting for the redirect on http://127.0.0.1:8888 ...")
    while "code" not in _captured_code:
        server.handle_request()

    code = _captured_code["code"]
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode())

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        print("No refresh_token in the response -- something went wrong:", payload, file=sys.stderr)
        sys.exit(1)

    print("\nSuccess! Add this as the SPOTIFY_REFRESH_TOKEN repo secret:\n")
    print(refresh_token)
    print("\n(This value is a credential -- treat it like a password, and never commit it.)")


if __name__ == "__main__":
    main()
