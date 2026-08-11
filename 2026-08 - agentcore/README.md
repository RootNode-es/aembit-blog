# Live test: self-hosted EC2 agent reaching GitHub via AgentCore Identity

This is a minimal, replicable version of the pattern covered in the article:
a self-hosted agent (plain EC2, not AgentCore Runtime) calling AgentCore
Identity as a standalone API to retrieve an access token for an external,
non-AWS resource -- GitHub.

It deliberately strips out the parts that aren't needed to see the core
exchange work: no ALB, no external company IdP, no Session Binding Service.
Those all matter for a production, multi-user deployment (covered in the
main article), but they'd only add setup steps without changing what you're
here to see -- AgentCore Identity brokering outbound trust to a non-AWS
target from infrastructure AWS doesn't manage.

## What you'll need

- An AWS account with permission to create IAM roles, EC2 instances, and
  Bedrock AgentCore resources
- Terraform >= 1.5
- An existing EC2 key pair in your target region (for SSH)
- Your own public IP address, for restricting SSH access
- A GitHub account

## Step 1 -- Register a GitHub OAuth App

AgentCore Identity needs a real OAuth client to broker access through.

1. Go to <https://github.com/settings/developers> -> **OAuth Apps** -> **New OAuth App**
2. Fill in:
   - **Application name**: anything, e.g. `agentcore-identity-demo`
   - **Homepage URL**: `https://example.com` (unused, just needs to be present)
   - **Authorization callback URL**: use a placeholder for now, e.g.
     `https://example.com/callback` -- you'll come back and fix this in Step 4,
     because AWS only generates the real callback URL once the credential
     provider exists.
3. Click **Register application**.
4. Note the **Client ID**, then click **Generate a new client secret** and
   note that too. You won't be able to see the secret again.

## Step 2 -- Deploy the infrastructure

```bash
cd agentcore-identity-ec2-github
terraform init
terraform apply \
  -var="github_client_id=<your client ID>" \
  -var="github_client_secret=<your client secret>" \
  -var="key_pair_name=<your EC2 key pair name>" \
  -var="my_ip_cidr=<your IP>/32"
```

This creates:

- An AgentCore Identity **workload identity** for the agent
- An AgentCore Identity **OAuth2 credential provider** for GitHub (built-in
  vendor, so you only supply the client ID/secret -- AWS pre-fills GitHub's
  OAuth endpoints)
- An IAM role for the EC2 instance, scoped to exactly two permissions:
  `GetWorkloadAccessToken` and `GetResourceOauth2Token`, each restricted to
  this specific workload identity and credential provider (not
  account-wide)
- A minimal dedicated VPC, public subnet, internet gateway, and route table
  (built explicitly rather than assumed, since not every AWS account has a
  default VPC)
- A `t3.micro` EC2 instance with that role attached, and a security group
  that only allows SSH from your IP

Don't commit your client ID/secret to version control. For anything beyond
a one-off test, pass them via a `.tfvars` file that's gitignored, or pull
the secret from AWS Secrets Manager instead of a CLI flag.

## Step 3 -- Get the real callback URL

Terraform doesn't currently expose the credential provider's generated
callback URL as an attribute, so this one step is manual:

1. Open the AWS Console -> **Bedrock AgentCore** -> **Identity** ->
   **Credential providers**
2. Click into `github-demo-provider` (or whatever you set
   `github_provider_name` to)
3. Copy its **OAuth2 callback URL**

## Step 4 -- Fix the GitHub OAuth App's callback URL

Back in your GitHub OAuth App settings (Step 1), replace the placeholder
callback URL with the real one from Step 3, and save.

This is the piece that makes the consent flow actually work: GitHub needs
to know it's allowed to redirect back to AWS's endpoint once you approve
access.

## Step 5 -- Run the agent

SSH into the instance using the IP from `terraform output instance_public_ip`:

```bash
ssh -i <your-key>.pem ec2-user@$(terraform output -raw instance_public_ip)
```

Copy `agent.py` onto the instance (`scp` it, or paste it directly), then run it:

```bash
python3 agent.py
```

First run, expect this:

```
1. Requesting a workload access token from AgentCore Identity...
   Done.
2. Requesting a GitHub OAuth2 token via AgentCore Identity...

No cached token yet -- this needs a one-time consent step.
Open this URL in a browser and approve access:

https://github.com/login/oauth/authorize?...

Waiting for consent to complete...
```

Open that URL on your laptop (not the EC2 instance), approve access, and
watch the script pick it up:

```
   Done -- token retrieved from the Token Vault.
3. Calling the GitHub API with the retrieved token...

Success. This EC2 agent authenticated to GitHub as: <your-github-username>
```

Run it again and it'll skip the browser step entirely -- the token is
already cached in the Token Vault, scoped to this workload identity.

## What just happened

- Your EC2 instance never held a long-lived GitHub credential. It asked
  AgentCore Identity for one, at request time.
- AgentCore Identity, not your code, handled the OAuth 2.0 mechanics --
  building the authorization URL, exchanging the code for a token, encrypting
  it at rest in the Token Vault.
- None of this depended on AgentCore Runtime, Cognito, or any AWS-managed
  compute. The trust chain only needed a workload identity and a correctly
  sequenced set of API calls -- which is the whole point of AgentCore
  Identity being usable as a standalone API.

## Cleaning up

```bash
terraform destroy
```

Then delete the GitHub OAuth App from <https://github.com/settings/developers>
if you don't intend to reuse it.

## Where this differs from a production deployment

This demo skips two things a real, multi-user, self-hosted deployment
needs, both covered in the main article:

- **Inbound auth against a real IdP.** Here, "who's calling" is just
  whoever runs the script. A production agent needs an ALB + OIDC (or
  equivalent) validating a real user's identity before requesting a
  workload token.
- **A Session Binding Service.** Because this demo has exactly one
  possible "user" (you, at the keyboard), there's no risk of the consent
  callback being hijacked or swapped between users. A multi-user deployment
  must verify that the person completing consent is the same person who
  started the request -- that's what the Session Binding Service is for.
