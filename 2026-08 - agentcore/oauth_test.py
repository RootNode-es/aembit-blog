import boto3
from bedrock_agentcore.services.identity import IdentityClient

REGION = "us-east-1"
WORKLOAD = "ec2-github-demo-agent"
USER_ID = "ec2-test-user"
PROVIDER = "oauth-client-qexzl"

print(f"Region:   {REGION}")
print(f"Workload: {WORKLOAD}")
print(f"User:     {USER_ID}")
print(f"Provider: {PROVIDER}")

identity = IdentityClient(REGION)

print("\n1. Getting workload access token...")

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

print("Workload token present:", bool(workload_token))
print("Workload token length:", len(workload_token) if workload_token else 0)

print("\n2. Calling GetResourceOauth2Token...")

client = boto3.client(
    "bedrock-agentcore",
    region_name=REGION,
)

response = client.get_resource_oauth2_token(
    workloadIdentityToken=workload_token,
    resourceCredentialProviderName=PROVIDER,
    scopes=["repo", "read:user"],
    resourceOauth2ReturnUrl="http://localhost:8080/oauth/callback",
    oauth2Flow="USER_FEDERATION",
    forceAuthentication=True,
)

print("\nSUCCESS")
print("Response keys:", list(response.keys()))

if "authorizationUrl" in response:
    print("\nGitHub authorization URL:")
    print(response["authorizationUrl"])