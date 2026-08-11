terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- Networking: a minimal dedicated VPC + public subnet, built here rather
#     than assumed. Not every account has a default VPC (newer or Control
#     Tower-managed accounts often don't), so this keeps the tutorial
#     reproducible regardless of account setup. ---
data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "demo" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.workload_name}-vpc"
  }
}

resource "aws_internet_gateway" "demo" {
  vpc_id = aws_vpc.demo.id

  tags = {
    Name = "${var.workload_name}-igw"
  }
}

resource "aws_subnet" "demo" {
  vpc_id                  = aws_vpc.demo.id
  cidr_block               = "10.0.1.0/24"
  availability_zone        = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch  = true

  tags = {
    Name = "${var.workload_name}-subnet"
  }
}

resource "aws_route_table" "demo" {
  vpc_id = aws_vpc.demo.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.demo.id
  }

  tags = {
    Name = "${var.workload_name}-rt"
  }
}

resource "aws_route_table_association" "demo" {
  subnet_id      = aws_subnet.demo.id
  route_table_id = aws_route_table.demo.id
}

# --- AgentCore Identity: a workload identity for this agent.
#     This is the identity every downstream call is scoped to -- the same
#     concept whether the agent runs on Runtime or, as here, on plain EC2. ---
resource "aws_bedrockagentcore_workload_identity" "agent" {
  name = var.workload_name
}

# --- AgentCore Identity: the built-in GitHub OAuth2 credential provider.
#     AWS pre-fills GitHub's OAuth endpoints -- you only supply the
#     client ID/secret from your own GitHub OAuth App. ---
resource "aws_bedrockagentcore_oauth2_credential_provider" "github" {
  name                       = var.github_provider_name
  credential_provider_vendor = "GithubOauth2"

  oauth2_provider_config {
    github_oauth2_provider_config {
      client_id     = var.github_client_id
      client_secret = var.github_client_secret
    }
  }
}

# --- IAM role for the EC2 instance. Deliberately scoped to exactly the
#     two AgentCore Identity calls this demo makes -- nothing broader. ---
resource "aws_iam_role" "agent_ec2" {
  name = "${var.workload_name}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "agent_identity_access" {
  name = "${var.workload_name}-identity-access"
  role = aws_iam_role.agent_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WorkloadAccessToken"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:GetWorkloadAccessToken"]
        Resource = [aws_bedrockagentcore_workload_identity.agent.workload_identity_arn]
      },
      {
        Sid      = "ResourceOauth2Token"
        Effect   = "Allow"
        Action   = ["bedrock-agentcore:GetResourceOauth2Token"]
        Resource = [aws_bedrockagentcore_oauth2_credential_provider.github.credential_provider_arn]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "agent_ec2" {
  name = "${var.workload_name}-ec2-profile"
  role = aws_iam_role.agent_ec2.name
}

# --- Security group: SSH from your IP only. No inbound app traffic needed --
#     this demo agent isn't fronted by a load balancer. ---
resource "aws_security_group" "agent_ec2" {
  name        = "${var.workload_name}-sg"
  description = "Allow SSH from a single trusted IP only"
  vpc_id      = aws_vpc.demo.id

  ingress {
    description = "SSH from the operator IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  egress {
    description = "All outbound -- needed to reach AgentCore Identity and GitHub"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- The EC2 instance: self-hosted compute, deliberately not Runtime. ---
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "agent" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.demo.id
  vpc_security_group_ids = [aws_security_group.agent_ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.agent_ec2.name
  key_name               = var.key_pair_name

  user_data = <<-EOF
    #!/bin/bash
    dnf install -y python3-pip
    pip3 install boto3 requests
  EOF

  tags = {
    Name = "${var.workload_name}-agent"
  }
}
