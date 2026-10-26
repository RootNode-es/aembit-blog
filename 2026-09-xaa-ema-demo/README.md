# Cross App Access / EMA demo: Okta → resource AS → MCP server

A runnable example of MCP Enterprise-Managed Authorization (Okta calls it Cross App Access),
using a real Okta org as the enterprise IdP. Three small Python programs play the other roles:

| Role | Code | What it shows |
| :- | :- | :- |
| Enterprise IdP | **your Okta org** | Signs the user in, evaluates policy, issues the ID-JAG |
| Requesting app (MCP client) | `client/run.py` | Sign-in, token exchange for an ID-JAG, redemption, tool calls |
| Resource authorization server | `resource_as/server.py` | Strict ID-JAG validation, user mapping, issuing its own token |
| MCP server | `mcp_server/server.py` | Per-call runtime policy and attributed audit log |

```
 client ──(1) auth code + PKCE──────────────▶ Okta        → ID token + refresh token
 client ──(2) token exchange (RFC 8693)─────▶ Okta        → ID-JAG   (Okta checks its policy)
 client ──(3) jwt-bearer grant (RFC 7523)───▶ resource AS → access token (AS validates the ID-JAG)
 client ──(4) tools/call + Bearer token─────▶ MCP server  → allow / deny per call
```

## 1. Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 2. Configure Okta

Follows Okta's guide *Add Cross App Access to Your OIDC Requesting Application*.

1. **Requesting app**: Applications → Create App Integration → OIDC → Web Application.
   - Grant types: Authorization Code **and Refresh Token**
   - Sign-in redirect URI: `http://localhost:8080/callback`
   - Assign your test user. Copy client ID/secret into `OKTA_CLIENT_ID` / `OKTA_CLIENT_SECRET`.
2. **Resource app**: a second OIDC app integration representing the MCP server.
   - Assign your test user.
   - On the **Resource Server** tab, enable Cross App Access and set **Issuer URL** to the value of
     `RESOURCE_AS_ISSUER` (default `http://localhost:9000`). If Okta rejects a non-HTTPS or
     localhost URL, expose port 9000 with a tunnel and use that https URL in both places.
3. **AI Agent**: Directory → AI Agents → register an agent.
   - User access: select the requesting app from step 1.
   - Resource connection: the resource app from step 2, with
     **AI agent's client ID registered in this app** = `RESOURCE_AS_CLIENT_ID` (default `demo-agent`),
     and scopes `notes.read notes.write` (or "Allow any scope").
   - Make sure the agent is **Active** and every section except Machine access is green.
4. Set `OKTA_ISSUER` to your org URL, e.g. `https://integrator-1234567.okta.com`.

## 3. Run

Three terminals, from the repo root:

```bash
uvicorn resource_as.server:app --port 9000      # resource authorization server
python -m mcp_server.server                     # MCP server on :8001/mcp
python -m client.run                            # opens the browser for Okta sign-in
```

The client prints every token decoded (ID token, ID-JAG, access token) and then calls the tools:

```
whoami                      -> who the MCP server thinks is calling (note "agent": null)
add_note / list_notes       -> allowed
delete_all_notes            -> DENIED: requires explicit user confirmation
delete_all_notes confirm    -> DENIED: requires role admin
```

To see the admin path, edit `resource_as/users.json` (created on first run), add `"admin"` to your
user's `roles`, and run the client again. Every decision is appended to `audit.log`.

`--subject id_token` exchanges the ID token instead of the refresh token, as the MCP spec's
diagram describes. Okta's guide uses the refresh token, so expect Okta to reject that variant.

## What each piece is (and isn't) responsible for

**Okta** decides whether this user, through this client, may connect to this resource, and records
that it issued the grant. Its decision is made once, when the ID-JAG is minted.

**The resource AS** (`validate_id_jag`) is where a SaaS vendor must be strict:

- `typ` must be `oauth-id-jag+jwt` (an ID token can't be replayed as a grant)
- signature from the trusted IdP's JWKS; `iss` = the trusted IdP; `aud` = this AS
- `client_id` in the ID-JAG must equal the authenticated client
- `resource` must be this MCP server, and the issued token is audience-bound to it
- `jti` is tracked so each ID-JAG is redeemed once
- scopes granted = approved by IdP ∩ allowed for client ∩ requested
- users are matched on `sub`; email is only a one-time linking fallback
- no refresh token is issued, so expiry sends the client back to the IdP and its policy

**The MCP server** (`authorize`) makes the decisions EMA can't, on every call: scope per tool,
role, confirmation for destructive actions, a write rate limit, and an audit record naming the
user, the client and the tool. What it *cannot* do with these tokens is tell agents apart: the
`agent` field is always empty, because nothing in the EMA flow identifies which agent inside the
client is acting. That's the gap a workload/agent identity layer has to fill.

## Notes

- Teaching code: in-memory replay cache and notes, a JSON user store, keys generated into `keys/`.
- The ID-JAG spec is still an IETF draft; check claim names and URNs against the current revision.
- The MCP Python SDK (2.x) also ships `IdentityAssertionOAuthProvider` (client) and an
  `exchange_identity_assertion` hook (server) for this flow. This demo writes the steps by hand so
  each one is visible.
