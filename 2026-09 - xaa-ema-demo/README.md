# Cross App Access / EMA demo: Okta → resource AS → MCP server

A runnable example of MCP Enterprise-Managed Authorization (EMA), which Okta calls Cross App
Access (XAA), using a real Okta org as the enterprise IdP. Three small Python programs play the
other roles:

| Role | Code | What it shows |
| :- | :- | :- |
| Enterprise IdP | **your Okta org** | Signs the user in, checks the approved connection, issues the ID-JAG |
| Client (MCP client) | `client/run.py` | Sign-in, token exchange for an ID-JAG, redemption, tool calls |
| Resource authorization server | `resource_as/server.py` | Strict ID-JAG validation, user mapping, issuing its own token |
| MCP server (notes service) | `mcp_server/server.py` | Per-call runtime policy and an attributed audit log |

```
 client ──(1) auth code + PKCE──────────────▶ Okta        → ID token + refresh token
 client ──(2) token exchange (RFC 8693)─────▶ Okta        → ID-JAG   (Okta checks the AI agent's connection)
 client ──(3) jwt-bearer grant (RFC 7523)───▶ resource AS → access token (the AS validates the ID-JAG)
 client ──(4) tools/call + Bearer token─────▶ MCP server  → allow / deny, per call
```

The notes service is deliberately minimal: notes are kept in memory, per user, and disappear
when the MCP server restarts.

## 1. Requirements

- **Python 3.10 or later** (3.12 recommended). The MCP Python SDK doesn't install on older
  versions. On macOS, the system Python is 3.9, so install a newer one, for example
  `brew install python@3.12`.
- A free **Okta Integrator** org: sign up at <https://developer.okta.com/signup/>.
- An **HTTPS URL for the resource authorization server.** Okta refuses an `http://localhost`
  issuer URL, so you need either a tunnel to port 9000 or a locally trusted certificate. See
  [section 4](#4-expose-the-resource-authorization-server-over-https).

## 2. Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version                 # must be 3.10+
python -m pip install -r requirements.txt
cp .env.example .env
```

Every new terminal needs `source .venv/bin/activate` before running anything.

## 3. Configure Okta

Okta keeps three objects for this demo. None of them is a running service: they're Okta's
records of the client, of the resource, and of the approved connection between them.

| Okta object | Represents |
| :- | :- |
| Requesting app | The client's registration at the IdP |
| Resource app | The resource authorization server: its issuer URL and scopes |
| AI agent | The approved connection: which users may use the client to reach the resource, with which scopes, and the client's ID at the resource |

Console labels below are as of October 2026 and may move.

### 3.1 Requesting app (the client)

**Applications → Create App Integration → OIDC - OpenID Connect → Web Application**

- **Client authentication:** Client secret. The client must be confidential.
- **Grant types:** Authorization Code **and Refresh Token**. Okta exchanges the refresh token for
  the ID-JAG, so this is required.
- **Proof of possession (DPoP):** leave off. The demo client doesn't send DPoP headers.
- **Sign-in redirect URI:** `http://localhost:8080/callback`
- **Assignments:** choose *Skip group assignment for now* and turn off *Federation Broker Mode*.
  After saving, open the **Assignments** tab and assign your test user.

Copy the **Client ID** and **Client secret** into `.env` as `OKTA_CLIENT_ID` and
`OKTA_CLIENT_SECRET`.

**Sign-on policy.** New apps may get a preset policy such as *Any two factors*. If your user
doesn't satisfy it, sign-in fails with `access_denied`. Either enroll the required factor (for
example Okta Verify, from the end-user dashboard under **Settings → Security Methods**), or
create a policy you control:

1. **Security → Authentication Policies → App sign-in → Add a policy**, named `Demo – XAA`.
2. Add a rule: conditions all on *Any*; access *Allowed after successful authentication*;
   authenticate with *Password / IdP + Another factor* (or *Password* only); no possession
   factor constraints.
3. On the requesting app's **Sign On** tab, set **User authentication** to `Demo – XAA`.

### 3.2 Resource app (the resource authorization server)

**Applications → Create App Integration → OIDC - OpenID Connect → Web Application**

- **Name:** for example *Notes Resource App*
- **Sign-in redirect URI:** any placeholder, for example `https://localhost/callback`. Users
  never sign in to it.
- **Assignments:** skip, then assign your test user on the **Assignments** tab.

Then enable Cross App Access:

**Machine Assignments → Callers → Cross App Access (XAA) → Edit → Enable**

- **Issuer URL:** the HTTPS URL of your resource AS, exactly the value of `RESOURCE_AS_ISSUER`
  in `.env` (no trailing slash).
- **Audience/tenant ID:** leave empty.
- **Scopes:** `notes.read` and `notes.write`, one per field.

If saving fails with *"Failed to save XAA configuration"*, the issuer URL is almost certainly not
HTTPS. See section 4.

Create **only one** resource app with XAA enabled. If you created several while experimenting,
deactivate the extra ones.

### 3.3 AI agent (the approved connection)

**Directory → AI Agents → register an agent**

- **Profile** and **Owners:** fill in, with your test user as owner.
- **User access:** *Select an existing app* → the requesting app from 3.1.
- **Resource connections** (not *Machine access*): add the resource app from 3.2, with
  - **AI agent's client ID registered in this app:** `demo-agent`, the same as
    `RESOURCE_AS_CLIENT_ID` in `.env`. Okta copies this value into the ID-JAG's `client_id`
    claim, and the resource AS checks it.
  - **Scopes:** `notes.read` and `notes.write`, or *Allow any scope*.
- Make sure the agent is **Active**. Every section should be green except **Machine access**,
  which this demo doesn't use. Machine access is the reverse direction: other services calling
  the agent with no user involved.

### 3.4 Finish `.env`

```dotenv
OKTA_ISSUER=https://integrator-1234567.okta.com     # https, no "-admin", no path
OKTA_CLIENT_ID=0oa...                                # requesting app → General
OKTA_CLIENT_SECRET=...                               # requesting app → General
CLIENT_REDIRECT_URI=http://localhost:8080/callback

RESOURCE_AS_ISSUER=https://<your-https-url>         # same as the Issuer URL in Okta
RESOURCE_AS_CLIENT_ID=demo-agent                     # same as the AI agent's resource connection
RESOURCE_AS_CLIENT_SECRET=<long random string>       # you choose it
```

`OKTA_ISSUER` must start with `https://`. With `http://`, Okta answers with a redirect and the
client stops; and the issuer must match the `iss` in Okta's tokens exactly anyway.

To generate `RESOURCE_AS_CLIENT_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep `.env` out of version control. It's already in `.gitignore`.

## 4. Expose the resource authorization server over HTTPS

Okta needs an HTTPS issuer URL for the resource app. Two ways to get one:

- **Any HTTPS tunnel to port 9000**, such as ngrok. Prefer one with a **fixed URL**: a quick
  tunnel gets a new URL each time it starts, and then `.env` and Okta must both be updated.
- **A locally trusted certificate** (for example with mkcert, plus a hosts-file entry) and
  `uvicorn --ssl-certfile ... --ssl-keyfile ...`. This works only if Okta saves the issuer URL
  without contacting it; Python processes must then trust the local CA via `SSL_CERT_FILE`.

Check that the URL reaches your resource AS (which must be running):

```bash
curl https://<your-https-url>/.well-known/oauth-authorization-server
```

The `issuer` in the response must be that same URL.

**Whenever the URL changes, update three things together:**

1. `RESOURCE_AS_ISSUER` in `.env`
2. The Issuer URL in the resource app's XAA configuration in Okta
3. Restart **both** servers, the resource AS and the MCP server. Both read the issuer at startup.

## 5. Run

Three terminals, from the repo's root folder, each with the virtual environment active. Start
them in this order:

```bash
uvicorn resource_as.server:app --port 9000      # 1. resource authorization server
python -m mcp_server.server                     # 2. MCP server on :8001/mcp
python -m client.run                            # 3. client: opens the browser for Okta sign-in
```

Plus your tunnel, if you use one.

The client prints each token decoded (ID token, ID-JAG, access token) and then calls the tools:

```
whoami                      -> sub, idp_sub, client_id "demo-agent", scope, roles, "agent": null
add_note                    -> added (1 notes)
list_notes                  -> XAA flow worked
delete_all_notes            -> DENIED: destructive action requires explicit user confirmation
delete_all_notes confirm    -> DENIED: requires role admin
```

To see the admin path, edit `resource_as/users.json` (created on your first sign-in), set your
user's `roles` to `["member", "admin"]`, and run the client again. No restart is needed. The
confirmed delete now succeeds. Every decision is appended to `audit.log`.

### Optional: call the tools from the MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

Connect with **Streamable HTTP** to `http://localhost:8001/mcp`. Under **Server Settings →
Custom Headers**, add `Authorization: Bearer <access token>`. Don't use the Inspector's OAuth
settings: this server only accepts tokens from the EMA flow.

The client doesn't print the raw access token by default. To get it, add this line after
`access_token = r.json()["access_token"]` in `redeem_id_jag` in `client/run.py`:

```python
    print("\nRAW ACCESS TOKEN:\n" + access_token + "\n")
```

Tokens last `ACCESS_TOKEN_TTL` seconds (300 by default). For longer Inspector sessions, raise it
in `.env` and restart the resource AS.

## 6. Troubleshooting

| Symptom | Cause | Fix |
| :- | :- | :- |
| `ModuleNotFoundError: No module named 'mcp'` | Virtual environment not active, or Python < 3.10 | Activate `.venv`; rebuild it with Python 3.10+ |
| `No matching distribution found for mcp` (*from versions: none*) | pip is running under Python < 3.10 | Rebuild the venv with Python 3.12; use `python -m pip` |
| `Redirect response '302 Moved Temporarily'` during discovery | `OKTA_ISSUER` uses `http://` | Use `https://` |
| Okta page: `400 Bad Request`, `access_denied` at sign-in | User not assigned, or the app's sign-on policy can't be satisfied | Assign the user; fix the policy (3.1). **Reports → System Log** gives the exact reason |
| *Failed to save XAA configuration* in Okta | Issuer URL isn't HTTPS | Use an HTTPS URL (section 4) |
| `unauthorized_client` … *Configured grant types: [authorization_code, refresh_token]* | No active AI agent links the requesting app to a resource app | Complete 3.2 and 3.3 |
| `invalid_target` … *must include a valid audience of the authorization server* | `RESOURCE_AS_ISSUER` doesn't match the Issuer URL in Okta (often: the tunnel URL changed) | Make them identical; restart both servers |
| `invalid_target` … *The token request contains an invalid target* | XAA is enabled on a different resource app than the AI agent's connection, or Okta doesn't accept the `resource` value | Keep one resource app and point the agent at it. If it persists, comment out the `"resource": MCP_RESOURCE` line in `request_id_jag` in `client/run.py`; the resource AS accepts an ID-JAG without a `resource` claim |
| `MCPError: Server returned an error response` at `session.initialize()` | The MCP server rejected the access token, usually because it still has the old issuer | Restart the MCP server; check its log for `rejected token:` |
| 401 from the MCP server in the Inspector | Access token expired | Run the client again for a fresh token |

## What each piece is (and isn't) responsible for

**Okta** decides whether this user, through this client, may connect to this resource, based on
the AI agent's resource connection and the user's sign-in. It decides once, when it issues the
ID-JAG. The AI agent object is Okta's way of storing that policy; the ID-JAG protocol leaves how
the IdP stores its policy to each IdP.

**The resource AS** (`validate_id_jag`) is where a SaaS vendor must be strict:

- `typ` must be `oauth-id-jag+jwt`, so an ID token can't be replayed as a grant
- signature from the trusted IdP's keys; `iss` = the trusted IdP; `aud` = this AS
- `client_id` in the ID-JAG must equal the authenticated client
- `resource`, when present, must be this MCP server, and the issued token is audience-bound to it
- `jti` is tracked so each ID-JAG is redeemed once. This is a hardening choice of this demo; the
  draft allows re-presenting an unexpired ID-JAG
- scopes granted = approved by the IdP ∩ allowed for the client ∩ requested
- users are matched on `sub`; email is only a one-time linking fallback
- no refresh token is issued, so expiry sends the client back to the IdP and its policy

**The MCP server** (`authorize`) makes the decisions EMA can't, on every call: scope per tool,
role, confirmation for destructive actions, a per-user write rate limit, and an audit record
naming the user, the client and the tool. What it can't do with these tokens is tell agents
apart: `agent` is always `null`, because nothing in the EMA flow requires or verifies which agent
inside the client is acting.

## Notes

- Teaching code: in-memory notes and replay cache, a JSON user store, keys generated into `keys/`.
- The ID-JAG specification is still an IETF draft; check claim names and URNs against the
  current revision.
- Okta exchanges the **refresh token** for the ID-JAG. The MCP spec's diagram exchanges the
  ID token; `python -m client.run --subject id_token` tries that variant.
- The MCP Python SDK (2.x) also ships an `IdentityAssertionOAuthProvider` (client) and an
  `exchange_identity_assertion` hook (server) for this flow. This demo writes each step by hand
  so it's visible.
