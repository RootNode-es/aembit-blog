#!/usr/bin/env python3
"""
Minimal AgentCore Identity demo -- run this on the EC2 instance created by
the accompanying Terraform config.

It performs the full outbound-auth exchange described in the article:

  1. This EC2 instance (self-hosted compute, not AgentCore Runtime) asks
     AgentCore Identity for a workload access token -- its own scoped
     identity, obtained by calling the standalone API directly.
  2. That workload token is exchanged for a GitHub OAuth2 access token via
     the GitHub credential provider. Since no token is cached yet, this
     triggers a 3-legged, user-consent OAuth flow: AgentCore Identity hands
     back an authorization URL, you approve access in a browser, and the
     resulting token lands in the Token Vault.
  3. The retrieved token is used to call the GitHub API directly.

Note on scope: this is a single-operator test flow, so it intentionally
skips building a Session Binding Service. That component is only required
in production, multi-user, self-hosted deployments, where your application
must cryptographically verify that the person completing OAuth consent is
the same person your own inbound auth (e.g. an ALB + Entra ID) already
authenticated -- see the main article for that architecture.
"""

import time
import boto3
import requests

REGION = "us-east-1"                            # must match your terraform aws_region
WORKLOAD_NAME = "ec2-github-demo-agent"          # must match var.workload_name
GITHUB_PROVIDER_NAME = "github-demo-provider"    # must match var.github_provider_name

client = boto3.client("bedrock-agentcore", region_name=REGION)


def get_workload_token() -> str:
    """Step 1: get this agent's own scoped identity from AgentCore Identity."""
    resp = client.get_workload_access_token(workloadName=WORKLOAD_NAME)
    return resp["workloadAccessToken"]


def get_github_token(workload_token: str) -> str:
    """Step 2: exchange the workload token for a GitHub OAuth2 access token,
    handling the one-time consent flow if no token is cached yet."""
    resp = client.get_resource_oauth2_token(
        workloadIdentityToken=workload_token,
        resourceCredentialProviderName=GITHUB_PROVIDER_NAME,
        scopes=["read:user"],
        oauth2Flow="USER_FEDERATION",
        forceAuthentication=False,
    )

    if "accessToken" in resp:
        return resp["accessToken"]

    auth_url = resp["authorizationUrl"]
    print("\nNo cached token yet -- this needs a one-time consent step.")
    print(f"Open this URL in a browser and approve access:\n\n{auth_url}\n")
    print("Waiting for consent to complete...")

    for _ in range(36):  # poll for ~3 minutes
        time.sleep(5)
        resp = client.get_resource_oauth2_token(
            workloadIdentityToken=workload_token,
            resourceCredentialProviderName=GITHUB_PROVIDER_NAME,
            scopes=["read:user"],
            oauth2Flow="USER_FEDERATION",
            forceAuthentication=False,
        )
        if "accessToken" in resp:
            return resp["accessToken"]
        if resp.get("sessionStatus") == "FAILED":
            raise RuntimeError("OAuth2 consent session failed -- re-run the script.")

    raise TimeoutError("Timed out waiting for OAuth consent. Re-run the script.")


def call_github(access_token: str) -> dict:
    """Step 3: use the retrieved token to call GitHub directly."""
    r = requests.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    print("1. Requesting a workload access token from AgentCore Identity...")
    workload_token = get_workload_token()
    print("   Done.")

    print("2. Requesting a GitHub OAuth2 token via AgentCore Identity...")
    github_token = get_github_token(workload_token)
    print("   Done -- token retrieved from the Token Vault.")

    print("3. Calling the GitHub API with the retrieved token...")
    user = call_github(github_token)
    print(f"\nSuccess. This EC2 agent authenticated to GitHub as: {user.get('login')}")
