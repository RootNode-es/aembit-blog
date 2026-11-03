"""Requesting app (the MCP client): runs the full Cross App Access / EMA flow against Okta.

  Step 3  OIDC sign-in at Okta (authorization code + PKCE)       -> ID token + refresh token
  Step 5  Token exchange at Okta (RFC 8693)                       -> ID-JAG
  Step 7  jwt-bearer grant at the resource AS (RFC 7523)          -> MCP access token
  Step 9  Call MCP tools with the access token

Run:  python -m client.run            (opens your browser for the Okta sign-in)
      python -m client.run --subject id_token   (exchange the ID token instead, as in the MCP spec)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (  # noqa: E402
    JWT_BEARER_GRANT,
    TOKEN_EXCHANGE_GRANT,
    TOKEN_TYPE_ID_JAG,
    TOKEN_TYPE_ID_TOKEN,
    TOKEN_TYPE_REFRESH,
    env,
    show_jwt,
)

OKTA_ISSUER = env("OKTA_ISSUER")
OKTA_CLIENT_ID = env("OKTA_CLIENT_ID")
OKTA_CLIENT_SECRET = env("OKTA_CLIENT_SECRET")
REDIRECT_URI = env("CLIENT_REDIRECT_URI", "http://localhost:8080/callback")
RESOURCE_AS_ISSUER = env("RESOURCE_AS_ISSUER")
RESOURCE_AS_CLIENT_ID = env("RESOURCE_AS_CLIENT_ID")
RESOURCE_AS_CLIENT_SECRET = env("RESOURCE_AS_CLIENT_SECRET")
MCP_RESOURCE = env("MCP_RESOURCE")
SCOPES = env("RESOURCE_SCOPES", "notes.read notes.write")


def discover(issuer: str, well_known: str) -> dict:
    r = httpx.get(f"{issuer}/.well-known/{well_known}", timeout=10)
    r.raise_for_status()
    return r.json()


def fail(step: str, response: httpx.Response) -> None:
    raise SystemExit(f"\n{step} failed ({response.status_code}): {response.text}")


# ── Step 3: sign in ──────────────────────────────────────────────────────────
def sign_in(okta: dict) -> dict:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": OKTA_CLIENT_ID,
        "response_type": "code",
        # offline_access: Okta exchanges the REFRESH token for the ID-JAG
        "scope": "openid profile email offline_access",
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    code = _wait_for_code(f"{okta['authorization_endpoint']}?{urlencode(params)}", state)
    r = httpx.post(
        okta["token_endpoint"],
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": OKTA_CLIENT_ID,
            "client_secret": OKTA_CLIENT_SECRET,
        },
    )
    if r.status_code != 200:
        fail("Sign-in token request", r)
    tokens = r.json()
    show_jwt("Step 3: ID token from Okta", tokens["id_token"])
    if "refresh_token" not in tokens:
        print("\n(no refresh token returned: enable the Refresh Token grant on the Okta app)")
    return tokens


def _wait_for_code(authorize_url: str, expected_state: str) -> str:
    result: dict = {}
    redirect = urlsplit(REDIRECT_URI)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = parse_qs(urlsplit(self.path).query)
            if urlsplit(self.path).path != redirect.path:
                self.send_response(404); self.end_headers(); return
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h3>Signed in. You can close this tab.</h3>")

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer((redirect.hostname, redirect.port or 80), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    print(f"Opening browser for Okta sign-in...\nIf it doesn't open, visit:\n{authorize_url}\n")
    webbrowser.open(authorize_url)
    while "code" not in result and "error" not in result:
        threading.Event().wait(0.2)
    server.server_close()
    if "error" in result:
        raise SystemExit(f"Okta returned {result['error']}: {result.get('error_description')}")
    if result.get("state") != expected_state:
        raise SystemExit("state mismatch")
    return result["code"]


# ── Step 5: ask the IdP for an ID-JAG ────────────────────────────────────────
def request_id_jag(okta: dict, tokens: dict, subject: str) -> str:
    if subject == "refresh_token":
        subject_token, subject_type = tokens["refresh_token"], TOKEN_TYPE_REFRESH
    else:
        subject_token, subject_type = tokens["id_token"], TOKEN_TYPE_ID_TOKEN
    r = httpx.post(
        okta["token_endpoint"],
        data={
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "requested_token_type": TOKEN_TYPE_ID_JAG,
            "subject_token": subject_token,
            "subject_token_type": subject_type,
            "audience": RESOURCE_AS_ISSUER,   # who will redeem it
            "scope": SCOPES,
            "client_id": OKTA_CLIENT_ID,      # client_secret_post, as in Okta's guide
            "client_secret": OKTA_CLIENT_SECRET,
        },
    )
    if r.status_code != 200:
        fail("Token exchange for ID-JAG", r)
    body = r.json()
    print(f"\nissued_token_type: {body.get('issued_token_type')}")
    id_jag = body["access_token"]  # the ID-JAG is returned in the access_token field
    show_jwt("Step 5: ID-JAG from Okta", id_jag)
    return id_jag


# ── Step 7: redeem the ID-JAG at the resource AS ─────────────────────────────
def redeem_id_jag(id_jag: str) -> str:
    resource_as = discover(RESOURCE_AS_ISSUER, "oauth-authorization-server")
    r = httpx.post(
        resource_as["token_endpoint"],
        auth=(RESOURCE_AS_CLIENT_ID, RESOURCE_AS_CLIENT_SECRET),  # client_secret_basic
        data={"grant_type": JWT_BEARER_GRANT, "assertion": id_jag, "scope": SCOPES},
    )
    if r.status_code != 200:
        fail("ID-JAG redemption", r)
    access_token = r.json()["access_token"]
    show_jwt("Step 7: access token from the resource AS", access_token)
    return access_token


# ── Step 9: use it ───────────────────────────────────────────────────────────
async def call_mcp(access_token: str) -> None:
    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(MCP_RESOURCE, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                print("\n── Step 9: MCP tools:", ", ".join(t.name for t in tools.tools))
                calls = [
                    ("whoami", {}),
                    ("list_notes", {}),                    
                    ("add_note", {"text": "XAA flow worked"}),
                    ("list_notes", {}),
                    ("delete_all_notes", {"confirm": True}),  # not an admin -> denied
                ]
                for name, args in calls:
                    result = await session.call_tool(name, args)
                    text = " ".join(getattr(c, "text", str(c)) for c in result.content)
                    print(f"  {name}({json.dumps(args)}) -> {text}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", choices=["refresh_token", "id_token"], default="refresh_token",
                        help="which Okta token to exchange for the ID-JAG (Okta uses refresh_token)")
    args = parser.parse_args()

    okta = discover(OKTA_ISSUER, "openid-configuration")
    tokens = sign_in(okta)
    id_jag = request_id_jag(okta, tokens, args.subject)
    access_token = redeem_id_jag(id_jag)
    asyncio.run(call_mcp(access_token))


if __name__ == "__main__":
    main()
