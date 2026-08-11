output "instance_public_ip" {
  description = "SSH into this to run agent.py"
  value       = aws_instance.agent.public_ip
}

output "workload_identity_name" {
  value = aws_bedrockagentcore_workload_identity.agent.name
}

output "workload_identity_arn" {
  value = aws_bedrockagentcore_workload_identity.agent.workload_identity_arn
}

output "github_credential_provider_arn" {
  value = aws_bedrockagentcore_oauth2_credential_provider.github.credential_provider_arn
}

output "next_step" {
  value = "AWS generates a unique OAuth2 callback URL for this credential provider -- Terraform does not currently expose it as an attribute. After apply, open the AWS Console: Bedrock AgentCore > Identity > Credential providers > ${var.github_provider_name}, copy its callback URL, and paste it into your GitHub OAuth App's 'Authorization callback URL' field (see README step 4)."
}
