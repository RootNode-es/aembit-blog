variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "workload_name" {
  description = "Name for the AgentCore Identity workload identity"
  type        = string
  default     = "ec2-github-demo-agent"
}

variable "github_provider_name" {
  description = "Name for the GitHub OAuth2 credential provider"
  type        = string
  default     = "github-demo-provider"
}

variable "github_client_id" {
  description = "Client ID from your GitHub OAuth App (see README step 1)"
  type        = string
}

variable "github_client_secret" {
  description = "Client secret from your GitHub OAuth App (see README step 1)"
  type        = string
  sensitive   = true
}

variable "instance_type" {
  description = "EC2 instance type for the demo agent"
  type        = string
  default     = "t3.micro"
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair, used for SSH access"
  type        = string
}

variable "my_ip_cidr" {
  description = "Your IP in CIDR form (e.g. 203.0.113.4/32), used to restrict SSH access to the instance"
  type        = string
}
