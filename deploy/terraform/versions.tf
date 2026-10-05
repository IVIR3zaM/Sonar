terraform {
  # use_lockfile in the backend needs Terraform 1.10.
  required_version = ">= 1.10"

  # State lives in Cloudflare R2. The bucket and endpoint come from backend.hcl and the credentials from
  # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (terraform init -backend-config=backend.hcl). R2 has no AWS account,
  # region or metadata service, so the checks that expect them are skipped.
  backend "s3" {
    key                         = "sonar/terraform.tfstate"
    region                      = "auto"
    use_path_style              = true
    use_lockfile                = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.52"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
