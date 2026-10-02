output "sonar_url" {
  description = "Public address of Sonar."
  value       = local.base_url
}

output "server_ipv4" {
  description = "Public IPv4 of the Gateway VM."
  value       = local.server.ipv4_address
}

output "volume_id" {
  description = "ID of the protected volume that holds the database."
  value       = hcloud_volume.data.id
}

output "api_token" {
  description = "Bearer token for /api/* (SONAR_API_TOKEN)."
  value       = random_password.api_token.result
  sensitive   = true
}
