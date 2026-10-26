"""Resource authorization server: redeems ID-JAGs (RFC 7523 jwt-bearer) for MCP access tokens.

This is the half of Cross App Access / Enterprise-Managed Authorization that a SaaS vendor
runs. Okta (the enterprise IdP) has already decided that this user, in this client, may
connect to us, and said so in a signed ID-JAG. Our job is to verify that claim strictly and
then issue OUR OWN short-lived access token for the MCP server. The IdP brokers trust; it does
not issue the token the MCP server accepts.

Run:  uvicorn resource_as.server:app --port 9000
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import sys
import time
from pathlib import Path

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import (  # noqa: E402
    ID_JAG_TYP,
    JWT_BEARER_GRANT,
    ROOT,
    env,
    load_or_create_rsa_key,
)

log = logging.getLogger("resource-as")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [resource-as] %(message)s")

# ── Configuration ────────────────────────────────────────────────────────────
ISSUER = env("RESOURCE_AS_ISSUER")            # must equal the Issuer URL set in Okta
TRUSTED_IDP_ISSUER = env("OKTA_ISSUER")       # the only IdP whose ID-JAGs we accept
MCP_RESOURCE = env("MCP_RESOURCE")            # the resource our tokens are audience-bound to
ACCESS_TOKEN_TTL = int(env("ACCESS_TOKEN_TTL", "300"))
STRICT_TYP = env("STRICT_ID_JAG_TYP", "true").lower() == "true"
CLOCK_SKEW = 30

# Clients registered at THIS authorization server. In Okta, the AI agent's resource
# connection must be configured with this same client ID ("AI agent's client ID registered
# in this app"), because Okta copies it into the ID-JAG's client_id claim.
CLIENTS = {
    env("RESOURCE_AS_CLIENT_ID"): {
        "secret": env("RESOURCE_AS_CLIENT_SECRET"),
        "allowed_scopes": {"notes.read", "notes.write"},
    }
}

USERS_FILE = ROOT / "resource_as" / "users.json"
SIGNING_KEY = load_or_create_rsa_key(ROOT / "keys" / "resource_as_private.pem")
KID = "resource-as-1"

# Keys published by the IdP, discovered from its OpenID configuration.
_idp_jwks: jwt.PyJWKClient | None = None
# jti -> exp, to reject replayed ID-JAGs for their whole lifetime.
_seen_jti: dict[str, int] = {}

app = FastAPI(title="Resource Authorization Server")


# ── Metadata (RFC 8414) and JWKS ─────────────────────────────────────────────
@app.get("/.well-known/oauth-authorization-server")
def metadata() -> dict:
    return {
        "issuer": ISSUER,
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "grant_types_supported": [JWT_BEARER_GRANT],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "authorization_grant_profiles_supported": ["urn:ietf:params:oauth:grant-profile:id-jag"],
        "scopes_supported": ["notes.read", "notes.write"],
    }


@app.get("/jwks")
def jwks() -> dict:
    public = jwt.algorithms.RSAAlgorithm.to_jwk(SIGNING_KEY.public_key(), as_dict=True)
    return {"keys": [{**public, "kid": KID, "use": "sig", "alg": "RS256"}]}


# ── Token endpoint ───────────────────────────────────────────────────────────
class OAuthError(Exception):
    def __init__(self, error: str, description: str, status: int = 400):
        self.error, self.description, self.status = error, description, status


@app.exception_handler(OAuthError)
def oauth_error(_: Request, exc: OAuthError) -> JSONResponse:
    log.warning("DENY %s: %s", exc.error, exc.description)
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description}, status_code=exc.status
    )


@app.post("/token")
async def token(request: Request) -> JSONResponse:
    form = dict(await request.form())
    client_id = authenticate_client(request, form)

    if form.get("grant_type") != JWT_BEARER_GRANT:
        raise OAuthError("unsupported_grant_type", "only the jwt-bearer grant is supported")
    assertion = form.get("assertion")
    if not assertion:
        raise OAuthError("invalid_request", "missing assertion")

    claims = validate_id_jag(assertion, client_id)
    user = resolve_user(claims)
    scopes = grant_scopes(claims, form.get("scope"), client_id)

    now = int(time.time())
    access_token = jwt.encode(
        {
            "iss": ISSUER,
            "aud": MCP_RESOURCE,             # bound to the resource named in the ID-JAG
            "sub": user["id"],               # OUR user id, not the IdP's
            "client_id": client_id,
            "scope": " ".join(sorted(scopes)),
            "roles": user["roles"],
            "idp_sub": claims["sub"],        # kept for audit correlation with the IdP
            "iat": now,
            "exp": now + ACCESS_TOKEN_TTL,
            "jti": secrets.token_urlsafe(16),
        },
        SIGNING_KEY,
        algorithm="RS256",
        headers={"kid": KID, "typ": "at+jwt"},
    )
    log.info("ISSUED access token sub=%s client=%s scope=%s", user["id"], client_id, " ".join(scopes))
    # No refresh token: when this expires the client goes back to the IdP for a new ID-JAG,
    # so the IdP's policy is re-evaluated and IdP-side revocation actually takes effect.
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "scope": " ".join(sorted(scopes)),
        },
        headers={"Cache-Control": "no-store"},
    )


def authenticate_client(request: Request, form: dict) -> str:
    """client_secret_basic or client_secret_post."""
    client_id = secret = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        client_id, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
    else:
        client_id, secret = form.get("client_id"), form.get("client_secret")
    client = CLIENTS.get(client_id or "")
    if not client or not secrets.compare_digest(client["secret"], secret or ""):
        raise OAuthError("invalid_client", "client authentication failed", 401)
    return client_id


def idp_jwks() -> jwt.PyJWKClient:
    """Discover the IdP's signing keys. Only outbound access to the IdP is needed."""
    global _idp_jwks
    if _idp_jwks is None:
        import httpx

        config = httpx.get(f"{TRUSTED_IDP_ISSUER}/.well-known/openid-configuration", timeout=10)
        config.raise_for_status()
        _idp_jwks = jwt.PyJWKClient(config.json()["jwks_uri"], cache_keys=True)
    return _idp_jwks


def validate_id_jag(assertion: str, client_id: str) -> dict:
    """Validate an ID-JAG per RFC 7523 §3 and the ID-JAG draft's processing rules."""
    try:
        header = jwt.get_unverified_header(assertion)
    except jwt.PyJWTError as e:
        raise OAuthError("invalid_grant", f"malformed assertion: {e}")

    # 1. Explicit type, so an ID token or access token can't be replayed as an ID-JAG.
    if header.get("typ") != ID_JAG_TYP:
        msg = f"typ is {header.get('typ')!r}, expected {ID_JAG_TYP!r}"
        if STRICT_TYP:
            raise OAuthError("invalid_grant", msg)
        log.warning("accepting assertion despite %s (STRICT_ID_JAG_TYP=false)", msg)

    # 2. Signature by the trusted IdP, issuer, audience = us, expiry.
    try:
        key = idp_jwks().get_signing_key_from_jwt(assertion).key
        claims = jwt.decode(
            assertion,
            key,
            algorithms=["RS256", "ES256"],
            issuer=TRUSTED_IDP_ISSUER,
            audience=ISSUER,
            leeway=CLOCK_SKEW,
            options={"require": ["iss", "sub", "aud", "exp", "iat", "jti", "client_id"]},
        )
    except jwt.PyJWTError as e:
        raise OAuthError("invalid_grant", f"ID-JAG rejected: {e}")

    # 3. The IdP issued this grant for the client that is presenting it, and nobody else.
    if claims["client_id"] != client_id:
        raise OAuthError(
            "invalid_grant",
            f"ID-JAG was issued for client {claims['client_id']!r}, presented by {client_id!r}",
        )

    # 4. It names our MCP server as the resource.
    if claims.get("resource") not in (None, MCP_RESOURCE):
        raise OAuthError("invalid_target", f"ID-JAG resource {claims.get('resource')!r} is not ours")

    # 5. One-time use.
    now = int(time.time())
    for jti, exp in list(_seen_jti.items()):
        if exp + CLOCK_SKEW < now:
            del _seen_jti[jti]
    if claims["jti"] in _seen_jti:
        raise OAuthError("invalid_grant", "ID-JAG has already been used")
    _seen_jti[claims["jti"]] = claims["exp"]

    log.info("ACCEPTED ID-JAG sub=%s client=%s scope=%s", claims["sub"], client_id, claims.get("scope"))
    return claims


def resolve_user(claims: dict) -> dict:
    """Map the IdP subject to a local account.

    sub is the stable identifier. email is only a fallback for linking accounts that existed
    before XAA was configured; matching on email alone is an account-takeover risk.
    """
    users = json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else {}
    for user_id, user in users.items():
        if user.get("idp_sub") == claims["sub"]:
            return {"id": user_id, **user}
    email = claims.get("email")
    for user_id, user in users.items():
        if email and user.get("email", "").lower() == email.lower() and not user.get("idp_sub"):
            user["idp_sub"] = claims["sub"]  # link once, then rely on sub from now on
            USERS_FILE.write_text(json.dumps(users, indent=2))
            log.info("LINKED existing user %s to idp_sub=%s by email", user_id, claims["sub"])
            return {"id": user_id, **user}

    if env("AUTO_PROVISION_USERS", "true").lower() != "true":
        raise OAuthError("invalid_grant", f"no local user for idp sub {claims['sub']}")
    user_id = f"u_{secrets.token_hex(4)}"
    users[user_id] = {"idp_sub": claims["sub"], "email": email, "roles": ["member"]}
    USERS_FILE.write_text(json.dumps(users, indent=2))
    log.info("PROVISIONED user %s for idp_sub=%s", user_id, claims["sub"])
    return {"id": user_id, **users[user_id]}


def grant_scopes(claims: dict, requested: str | None, client_id: str) -> set[str]:
    """Granted = what the IdP approved ∩ what this client may have ∩ what was asked for."""
    approved = set((claims.get("scope") or "").split())
    allowed = CLIENTS[client_id]["allowed_scopes"]
    asked = set(requested.split()) if requested else approved
    granted = approved & allowed & asked
    if not granted:
        raise OAuthError("invalid_scope", f"no grantable scopes (approved={approved}, asked={asked})")
    return granted
