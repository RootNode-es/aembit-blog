terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.55.0"
    }

    awscc = {
      source  = "hashicorp/awscc"
      version = ">= 1.92.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "awscc" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "workload_identity_name" {
  type    = string
  default = "ec2-github-demo-agent"
}

variable "github_provider_name" {
  type    = string
  default = "github-provider"
}

# This account has no default VPC (common for newer or Control
# Tower-managed accounts), so a minimal dedicated VPC is created here
# instead of assuming one exists.
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "demo" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.workload_identity_name}-vpc"
  }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id

  tags = {
    Name = "${var.workload_identity_name}-igw"
  }
}

resource "aws_subnet" "demo" {
  vpc_id                  = aws_vpc.demo.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.workload_identity_name}-subnet"
  }
}

resource "aws_route_table" "demo" {
  vpc_id = aws_vpc.demo.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }

  tags = {
    Name = "${var.workload_identity_name}-rt"
  }
}

resource "aws_route_table_association" "demo" {
  subnet_id      = aws_subnet.demo.id
  route_table_id = aws_route_table.demo.id
}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["137112412989"] # Amazon

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

data "aws_caller_identity" "current" {}

# Explicitly create the workload identity that the local AgentCore SDK
# will use via .agentcore.json. This avoids the SDK creating a random
# workload identity during local authentication.
resource "awscc_bedrockagentcore_workload_identity" "ec2" {
  name = var.workload_identity_name

  tags = [
    {
      key   = "Name"
      value = var.workload_identity_name
    },
    {
      key   = "Purpose"
      value = "EC2 AgentCore Identity GitHub 3LO test"
    }
  ]
}

resource "aws_iam_role" "ec2" {
  name = "ec2-github-demo-agent-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Permissions needed by the EC2-hosted AgentCore application.
#
# The workload identity itself is created by Terraform, so
# CreateWorkloadIdentity is deliberately NOT granted here.
resource "aws_iam_role_policy" "agentcore" {
  name = "agentcore-identity-and-bedrock"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WorkloadAccessToken"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetWorkloadAccessToken",
          "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
        ]
        Resource = [
          "arn:aws:bedrock-agentcore:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workload-identity-directory/default",
          awscc_bedrockagentcore_workload_identity.ec2.workload_identity_arn
        ]
      },
      {
        Sid    = "ResourceOAuth"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetResourceOauth2Token",
          "bedrock-agentcore:CompleteResourceTokenAuth"
        ]
        Resource = "*"
      },
            {

        Sid    = "AgentCoreOAuthSecret"

        Effect = "Allow"

        Action = [

          "secretsmanager:GetSecretValue"

        ]

Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:bedrock-agentcore-identity!default/oauth2/*"
      },
      {
        Sid    = "InvokeClaude"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "ec2-github-demo-agent-profile"
  role = aws_iam_role.ec2.name
}

resource "aws_security_group" "ec2" {
  name        = "ec2-github-demo-agent-sg"
  description = "Security group for AgentCore Identity EC2 test"
  vpc_id      = aws_vpc.demo.id

  # No inbound SSH is required. Use AWS Systems Manager Session Manager.
  egress {
    description = "Allow outbound HTTPS and other required traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "ec2-github-demo-agent-sg"
  }
}

locals {
  agent_code = <<-PYTHON
    import asyncio
    import os
    import traceback

    from bedrock_agentcore import BedrockAgentCoreApp
    from bedrock_agentcore.identity.auth import requires_access_token
    from strands import Agent, tool

    PROVIDER_NAME = "${var.github_provider_name}"
    SCOPES = ["repo", "read:user"]

    github_access_token = None

    app = BedrockAgentCoreApp()


    def on_auth_url(url: str):
        print("\\n" + "=" * 70, flush=True)
        print("GITHUB AUTHORIZATION REQUIRED", flush=True)
        print("=" * 70, flush=True)
        print("Open this URL in your local browser:", flush=True)
        print("", flush=True)
        print(url, flush=True)
        print("", flush=True)
        print("=" * 70 + "\\n", flush=True)


    @tool
    def inspect_github_repos() -> str:
        """Tool that requires authentication to access GitHub repos."""
        global github_access_token

        print("[GitHub tool] invoked", flush=True)

        if not github_access_token:
            print("[GitHub tool] no access token", flush=True)
            return "Authentication required for GitHub access"

        print("[GitHub tool] access token available", flush=True)

        headers = {
            "Authorization": f"Bearer {github_access_token}",
            "Accept": "application/vnd.github+json",
        }

        # TODO: Make your actual GitHub API request here.
        # Example:
        # response = requests.get(
        #     "https://api.github.com/user/repos",
        #     headers=headers,
        #     timeout=30,
        # )
        # return response.text

        return "GitHub authentication successful"


    @requires_access_token(
        provider_name=PROVIDER_NAME,
        scopes=SCOPES,
        auth_flow="USER_FEDERATION",
        on_auth_url=on_auth_url,
        force_authentication=True,
    )
    async def need_token_3LO_async(*, access_token: str) -> str:
        global github_access_token

        print("[AgentCore Identity] access token received", flush=True)
        print(f"[AgentCore Identity] token length: {len(access_token)}", flush=True)

        github_access_token = access_token
        return access_token


    agent = Agent(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        tools=[inspect_github_repos],
    )


    async def agent_task(user_message: str):
        global github_access_token

        print(f"[Agent] prompt: {user_message}", flush=True)

        response = agent(user_message)

        if "Authentication required" in str(response.message):
            print("[Agent] GitHub authentication required", flush=True)
            await need_token_3LO_async(access_token="")
            print("[Agent] Retrying after authentication", flush=True)
            response = agent(user_message)

        return response


    @app.entrypoint
    async def agent_invocation(payload):
        user_message = payload.get(
            "prompt",
            "Inspect my GitHub repositories",
        )

        return await agent_task(user_message)


    if __name__ == "__main__":
        print("Starting AgentCore application...", flush=True)
        print(f"AWS region: {os.environ.get('AWS_REGION')}", flush=True)
        print(f"GitHub provider: {PROVIDER_NAME}", flush=True)
        print(f"Scopes: {SCOPES}", flush=True)
        print("Workload identity: ${var.workload_identity_name}", flush=True)
        app.run()
  PYTHON
}

resource "aws_instance" "agentcore" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.demo.id
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids = [aws_security_group.ec2.id]

  user_data_replace_on_change = true

  user_data = <<-USERDATA
    #!/bin/bash
    set -euxo pipefail

    exec > >(tee /var/log/agentcore-bootstrap.log | logger -t agentcore-bootstrap -s 2>/dev/console) 2>&1

    dnf install -y python3.11 python3.11-pip

    useradd -m -s /bin/bash agentcore || true

    mkdir -p /home/agentcore/app
    chown -R agentcore:agentcore /home/agentcore

    sudo -u agentcore python3.11 -m venv /home/agentcore/venv

    sudo -u agentcore /home/agentcore/venv/bin/pip install --upgrade pip
    sudo -u agentcore /home/agentcore/venv/bin/pip install \
      bedrock-agentcore \
      strands-agents \
      httpx

    cat > /home/agentcore/app/.agentcore.json <<'AGENTCORE_CONFIG'
    {
      "workload_identity_name": "${var.workload_identity_name}",
      "user_id": "ec2-test-user"
    }
    AGENTCORE_CONFIG

    cat > /home/agentcore/app/agent.py <<'PYTHON'
    ${indent(4, local.agent_code)}
    PYTHON

    chown -R agentcore:agentcore /home/agentcore/app

    cat > /etc/systemd/system/agentcore-github.service <<'SERVICE'
    [Unit]
    Description=AgentCore GitHub Identity Demo
    After=network-online.target
    Wants=network-online.target

    [Service]
    Type=simple
    User=agentcore
    WorkingDirectory=/home/agentcore/app
    Environment=AWS_REGION=${var.aws_region}
    Environment=AWS_DEFAULT_REGION=${var.aws_region}
    Environment=PYTHONUNBUFFERED=1
    ExecStart=/home/agentcore/venv/bin/python /home/agentcore/app/agent.py
    Restart=on-failure
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
    SERVICE

    systemctl daemon-reload
    systemctl enable --now agentcore-github.service

    echo "AgentCore EC2 bootstrap complete."
  USERDATA

  tags = {
    Name = "ec2-github-demo-agent"
  }

  depends_on = [
    aws_iam_role_policy.agentcore,
    aws_iam_role_policy_attachment.ssm,
    awscc_bedrockagentcore_workload_identity.ec2
  ]
}

output "instance_id" {
  value = aws_instance.agentcore.id
}

output "private_ip" {
  value = aws_instance.agentcore.private_ip
}

output "workload_identity_arn" {
  value = awscc_bedrockagentcore_workload_identity.ec2.workload_identity_arn
}

output "workload_identity_name" {
  value = awscc_bedrockagentcore_workload_identity.ec2.name
}

output "ssm_command" {
  value = "aws ssm start-session --target ${aws_instance.agentcore.id} --region ${var.aws_region}"
}

output "logs_command" {
  value = "aws ssm start-session --target ${aws_instance.agentcore.id} --region ${var.aws_region} --document-name AWS-StartInteractiveCommand --parameters command='sudo journalctl -u agentcore-github.service -f'"
}
