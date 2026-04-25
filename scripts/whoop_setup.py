"""One-time WHOOP OAuth setup.

Run locally to get your refresh token, then paste into DO env vars.

Usage:
    1. Create a WHOOP developer app: https://developer.whoop.com
       - Set redirect URI to: http://localhost:8765/callback
       - Note your Client ID and Client Secret
    2. Set env vars: WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET
    3. Run: python -m scripts.whoop_setup
    4. Browser opens → log into WHOOP → authorise
    5. Script prints your refresh token. Save it as WHOOP_REFRESH_TOKEN.
"""
import os
import secrets
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

CLIENT_ID = os.environ.get("WHOOP_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("WHOOP_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8765/callback"
SCOPE = "offline read:recovery read:cycles read:sleep read:workout read:profile"

AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

state = secrets.token_urlsafe(16)
auth_code: str | None = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        if params.get("state") != state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"State mismatch")
            return
        auth_code = params.get("code")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<h1>OK</h1><p>You can close this tab and return to your terminal.</p>"
        )

    def log_message(self, *_):
        pass


def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit("Set WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET first")

    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": state,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print("Opening browser for WHOOP authorisation…")
    print(f"If it doesn't open, visit:\n{url}\n")
    webbrowser.open(url)

    server = HTTPServer(("localhost", 8765), Handler)
    while auth_code is None:
        server.handle_request()

    print("Got auth code, exchanging for tokens…")
    r = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
    )
    r.raise_for_status()
    tokens = r.json()

    print("\n✓ Success.\n")
    print("Add this to your DO App Platform env vars:\n")
    print(f"  WHOOP_REFRESH_TOKEN={tokens['refresh_token']}")
    print(f"\n(access token expires in {tokens.get('expires_in')}s; ignore — bot refreshes automatically)")


if __name__ == "__main__":
    main()
