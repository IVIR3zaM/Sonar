variable "hcloud_token" {
  description = "Hetzner Cloud API token with read/write access to the project holding the Gateway VM."
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token allowed to edit DNS records in the zone."
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID of the domain that holds sonar_hostname."
  type        = string
}

variable "sonar_hostname" {
  description = "Public FQDN of Sonar, for example sonar.example.com."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z]{2,}$", var.sonar_hostname))
    error_message = "sonar_hostname must be a lowercase fully qualified domain name, for example sonar.example.com."
  }
}

variable "google_client_id" {
  description = "Client ID of the Google OAuth client."
  type        = string
}

variable "google_client_secret" {
  description = "Client secret of the Google OAuth client."
  type        = string
  sensitive   = true
}

variable "allowed_emails" {
  description = "Every email allowed to sign in; each apply replaces the access list with exactly these."
  type        = list(string)

  validation {
    condition     = length(var.allowed_emails) >= 1
    error_message = "allowed_emails needs at least one email."
  }

  validation {
    condition     = alltrue([for email in var.allowed_emails : length(split("@", trimspace(email))) == 2])
    error_message = "Every entry of allowed_emails must contain exactly one @."
  }
}

variable "sonar_git_ref" {
  description = "Full commit SHA on main to deploy."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.sonar_git_ref))
    error_message = "sonar_git_ref must be a full 40-character lowercase commit SHA."
  }
}

variable "sonar_repo_url" {
  description = "Public Git URL of Sonar, cloned without credentials."
  type        = string
  default     = "https://github.com/IVIR3zaM/Sonar.git"
}

variable "uv_version" {
  description = "uv version installed on the VM."
  type        = string
  default     = "0.8.17"
}

variable "volume_size" {
  description = "Size in GB of the volume that holds the SQLite database."
  type        = number
  default     = 10
}

variable "server_label_selector" {
  description = "Hetzner label selector that matches exactly one server: the Gateway VM."
  type        = string
  default     = "project=gateway"
}

variable "ssh_private_key_path" {
  description = "Private key that logs in as root on the Gateway VM."
  type        = string
  default     = "~/.ssh/id_ed25519"
}
