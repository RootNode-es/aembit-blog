"""Notes MCP server protected by tokens from the resource authorization server.

Everything EMA decided happened before this process saw a single request: the IdP approved
the connection and our AS turned that into an access token. What this server adds is the part
EMA cannot do: a decision on EVERY tool call, using who is calling, which tool, which
arguments, and what has happened recently.

Run:  python -m mcp_server.server
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

import jwt
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT, env  # noqa: E402

log = logging.getLogger("mcp-server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [mcp-server] %(message)s")

AS_ISSUER = env("RESOURCE_AS_ISSUER")
MCP_RESOURCE = env("MCP_RESOURCE")
WRITES_PER_MINUTE = int(env("WRITES_PER_MINUTE", "5"))
AUDIT_LOG = ROOT / "audit.log"


# ── Token verification: is this a valid token from OUR AS, for THIS server? ──
class ResourceASTokenVerifier:
    def __init__(self) -> None:
        self._jwks = jwt.PyJWKClient(f"{AS_ISSUER}/jwks", cache_keys=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=AS_ISSUER,
                audience=MCP_RESOURCE,
                options={"require": ["exp", "sub", "client_id", "scope"]},
            )
        except jwt.PyJWTError as e:
            log.warning("rejected token: %s", e)
            return None
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=claims["scope"].split(),
            expires_at=claims["exp"],
            resource=claims["aud"],
            subject=claims["sub"],
            claims=claims,
        )


mcp = MCPServer(
    "notes",
    instructions="A per-user notes service, used to demonstrate runtime authorization.",
    token_verifier=ResourceASTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AS_ISSUER,
        resource_server_url=MCP_RESOURCE,
        required_scopes=["notes.read"],
        validate_token_resource=True,  # refuse tokens issued for another resource
    ),
)


# ── Runtime policy: is THIS call acceptable, right now? ─────────────────────
class Denied(Exception):
    pass


_writes: dict[str, deque[float]] = defaultdict(deque)


def authorize(tool: str, args: dict, *, scope: str, role: str | None = None,
              write: bool = False, needs_confirmation: bool = False) -> dict:
    """Evaluate one tool call and write an attributed audit record either way."""
    token = get_access_token()
    claims = token.claims if token and token.claims else {}
    principal = {
        "user": claims.get("sub"),
        "idp_sub": claims.get("idp_sub"),
        "client_id": claims.get("client_id"),
        # The gap the article is about: nothing in an EMA-derived token says WHICH agent inside
        # the client is calling. A research sub-agent and a coding agent look identical here.
        "agent": claims.get("agent"),
    }
    reason = None
    if not token:
        reason = "no authenticated principal"
    elif scope not in token.scopes:
        reason = f"missing scope {scope}"
    elif needs_confirmation and args.get("confirm") is not True:
        reason = "destructive action requires explicit user confirmation (confirm=true)"
    elif role and role not in claims.get("roles", []):
        reason = f"requires role {role}"
    elif write:
        window = _writes[principal["user"]]
        now = time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= WRITES_PER_MINUTE:
            reason = f"rate limit: more than {WRITES_PER_MINUTE} writes per minute"
        else:
            window.append(now)

    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **principal,
        "tool": tool,
        "args": args,
        "decision": "deny" if reason else "allow",
        "reason": reason,
    }
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")
    log.info("%s %s user=%s client=%s %s", record["decision"].upper(), tool,
             principal["user"], principal["client_id"], reason or "")
    if reason:
        raise Denied(reason)
    return principal


# ── Tools ────────────────────────────────────────────────────────────────────
NOTES: dict[str, list[str]] = defaultdict(list)


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Denied as e:
        return f"DENIED: {e}"


@mcp.tool()
def whoami() -> dict:
    """Show the identity this server sees for the caller."""
    token = get_access_token()
    claims = token.claims if token and token.claims else {}
    return {k: claims.get(k) for k in ("sub", "idp_sub", "client_id", "scope", "roles", "agent")}


@mcp.tool()
def list_notes() -> list[str] | str:
    """List the caller's notes."""
    def run():
        p = authorize("list_notes", {}, scope="notes.read")
        return NOTES[p["user"]]
    return _guard(run)


@mcp.tool()
def add_note(text: str) -> str:
    """Add a note."""
    def run():
        p = authorize("add_note", {"text": text}, scope="notes.write", write=True)
        NOTES[p["user"]].append(text)
        return f"added ({len(NOTES[p['user']])} notes)"
    return _guard(run)


@mcp.tool()
def delete_all_notes(confirm: bool = False) -> str:
    """Delete every note. Admin only, and only with explicit confirmation."""
    def run():
        p = authorize("delete_all_notes", {"confirm": confirm}, scope="notes.write",
                      role="admin", write=True, needs_confirmation=True)
        count = len(NOTES.pop(p["user"], []))
        return f"deleted {count} notes"
    return _guard(run)


if __name__ == "__main__":
    from urllib.parse import urlsplit

    url = urlsplit(MCP_RESOURCE)
    mcp.run(
        "streamable-http",
        host=url.hostname or "127.0.0.1",
        port=url.port or 8001,
        streamable_http_path=url.path or "/mcp",
    )
