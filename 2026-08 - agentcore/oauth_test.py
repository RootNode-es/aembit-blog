import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

import boto3
from bedrock_agentcore.services.identity import IdentityClient

# ============================================================
# Configuration
# ============================================================

REGION = "us-east-1"
WORKLOAD = "ec2-github-demo-agent"
USER_ID = "ec2-test-user"
PROVIDER = "oauth-client"

CALLBACK_HOST = "0.0.0.0"
CALLBACK_PORT = 8080

# For a public EC2 callback, set this to the public HTTPS URL:
#
# export OAUTH2_RETURN_URL="https://your-public-host/oauth/callback"
#
# For local testing you can use:
#
# export OAUTH2_RETURN_URL="http://localhost:8080/oauth/callback"
#
RETURN_URL = os.environ.get(
    "OAUTH2_RETURN_URL",
    "http://localhost:8080/oauth/callback",
)


print(f"Region:   {REGION}")
print(f"Workload: {WORKLOAD}")
print(f"User:     {USER_ID}")
print(f"Provider: {PROVIDER}")
print(f"Callback: {RETURN_URL}")


# ============================================================
# AWS clients
# ============================================================

identity = IdentityClient(REGION)

client = boto3.client(
    "bedrock-agentcore",
    region_name=REGION,
)


# Used to keep the process alive until the OAuth callback arrives.
oauth_completed = threading.Event()


# ============================================================
# OAuth callback endpoint
# ============================================================

class OAuthCallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path != "/oauth/callback":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        params = parse_qs(parsed.query)

        print()
        print("=" * 70)
        print("AGENTCORE OAUTH CALLBACK RECEIVED")
        print("=" * 70)

        print("Callback URL:", self.path)

        # AgentCore sends the OAuth session URI as session_id.
        session_id = params.get("session_id", [None])[0]

        error = params.get("error", [None])[0]
        error_description = params.get(
            "error_description",
            [""],
        )[0]

        if error:
            print("OAuth error:", error)
            print("Description:", error_description)

            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                f"""
                <html>
                  <body>
                    <h1>Authorization failed</h1>
                    <p>{error}</p>
                    <p>{error_description}</p>
                  </body>
                </html>
                """.encode()
            )

            oauth_completed.set()
            return

        if not session_id:
            print("ERROR: no session_id received")

            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing session_id")
            return

        print()
        print("Session ID received:")
        print(session_id)

        print()
        print("Completing AgentCore OAuth session...")
        print(f"User ID: {USER_ID}")

        try:
            client.complete_resource_token_auth(
                sessionUri=session_id,
                userIdentifier={
                    "userId": USER_ID
                },
            )

            print()
            print("OAuth session successfully completed.")
            print("The credential is now available through AgentCore Identity.")

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                b"""
                <!DOCTYPE html>
                <html>
                  <head>
                    <title>Authorization successful</title>
                  </head>
                  <body>
                    <h1>Authorization successful</h1>
                    <p>
                      GitHub authorization has been completed.
                    </p>
                    <p>
                      You can close this window and return to the EC2 agent.
                    </p>
                  </body>
                </html>
                """
            )

            oauth_completed.set()

        except Exception as e:
            print()
            print("ERROR completing OAuth session:")
            print(type(e).__name__)
            print(str(e))

            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(
                f"Failed to complete OAuth session: {e}".encode()
            )


    def log_message(self, format, *args):
        # Keep the output focused on the OAuth flow.
        pass


def start_callback_server():
    server = HTTPServer(
        (CALLBACK_HOST, CALLBACK_PORT),
        OAuthCallbackHandler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    print()
    print("=" * 70)
    print("OAUTH CALLBACK SERVER")
    print("=" * 70)
    print(
        f"Listening on http://{CALLBACK_HOST}:{CALLBACK_PORT}/oauth/callback"
    )
    print(f"Public return URL: {RETURN_URL}")

    return server


# ============================================================
# Start callback server
# ============================================================

server = start_callback_server()

# ============================================================
# Step 2 - Get workload access token
# ============================================================

print()
print("=" * 70)
print("STEP 2 - GET WORKLOAD ACCESS TOKEN")
print("=" * 70)

result = identity.get_workload_access_token(
    workload_name=WORKLOAD,
    user_id=USER_ID,
)

print("Result type:", type(result))

if isinstance(result, dict):
    print("Result keys:", list(result.keys()))
    workload_token = result.get("workloadAccessToken")
else:
    workload_token = result

print(
    "Workload token present:",
    bool(workload_token),
)

print(
    "Workload token length:",
    len(workload_token) if workload_token else 0,
)

# ============================================================
# Step 4 - Start OAuth flow with get_resource_oauth2_token
# ============================================================

print()
print("=" * 70)
print("STEP 4 - START GITHUB OAUTH FLOW")
print("=" * 70)

response = client.get_resource_oauth2_token(
    workloadIdentityToken=workload_token,
    resourceCredentialProviderName=PROVIDER,
    scopes=["repo", "read:user"],
    resourceOauth2ReturnUrl=RETURN_URL,
    oauth2Flow="USER_FEDERATION",
    forceAuthentication=True,
)

print()
print("Response keys:", list(response.keys()))

if "authorizationUrl" not in response:
    print("No authorization URL was returned.")
    print(response)
    raise SystemExit(1)

authorization_url = response["authorizationUrl"]

print()
print("=" * 70)
print("STEP 6 - AUTHORIZE WITH GITHUB")
print("=" * 70)

print()
print("Open this URL in your browser:")
print()
print(authorization_url)
print()

# ============================================================
# Step 4 - Wait for callback
# ============================================================

print("=" * 70)
print("STEP 7 - WAITING FOR GITHUB CALLBACK")
print("=" * 70)

print()
print(f"Waiting on {RETURN_URL}...")
print()
print("The callback will be handled by THIS EC2 process.")
print("The session_id will be passed to CompleteResourceTokenAuth.")
print()

oauth_completed.wait()

print()
print("=" * 70)
print("STEP 9 - OAUTH FLOW COMPLETED")
print("=" * 70)

print()
print("The EC2 agent completed the OAuth session.")
print()
# ============================================================
# Step 6 - Retrieve the GitHub access token
# ============================================================

print()
print("=" * 70)
print("STEP 6 - RETRIEVE GITHUB ACCESS TOKEN")
print("=" * 70)

print()
print("Requesting the OAuth credential from AgentCore Identity...")
print("The credential is retrieved from the Token Vault.")

token_response = client.get_resource_oauth2_token(
    workloadIdentityToken=workload_token,
    resourceCredentialProviderName=PROVIDER,
    scopes=["repo", "read:user"],
    oauth2Flow="USER_FEDERATION",
    forceAuthentication=False,
)

print()
print("Response keys:", list(token_response.keys()))

# The exact field should be inspected rather than printing
# the credential itself.
github_access_token = token_response.get("accessToken")

print()
print("=" * 70)
print("STEP 10 - GITHUB ACCESS TOKEN")
print("=" * 70)

print()
print("Access token received:", bool(github_access_token))

if github_access_token:
    print("Access token length:", len(github_access_token))

    # Just for test, in production NEVER print the actual token.
    print("Access token value: ", github_access_token)

else:
    print("No access token was returned.")
    print("Full response:")
    print(token_response)
# ============================================================
# Keep the server alive briefly so the browser can receive
# the successful response.
# ============================================================

server.shutdown()
server.server_close()

print()
print("Callback server stopped.")
