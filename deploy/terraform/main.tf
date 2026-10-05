provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Sonar shares the existing Gateway VM; Terraform only looks it up, never manages it.
data "hcloud_servers" "gateway" {
  with_selector = var.server_label_selector

  lifecycle {
    postcondition {
      condition     = length(self.servers) == 1
      error_message = "Label selector \"${var.server_label_selector}\" must match exactly one Hetzner server (the Gateway VM)."
    }
  }
}

# The deploying machine's public IPv4, re-read on every plan so a changing IP still gets in.
data "http" "my_ip_primary" {
  url = "https://api.ipify.org"

  retry {
    attempts = 2
  }
}

data "http" "my_ip_fallback" {
  url = "https://ipv4.icanhazip.com"

  retry {
    attempts = 2
  }
}

locals {
  detected_ip = try(
    chomp(data.http.my_ip_primary.response_body),
    chomp(data.http.my_ip_fallback.response_body),
  )
  ssh_allow_cidrs = length(var.ssh_allow_cidrs) == 0 ? ["${local.detected_ip}/32"] : var.ssh_allow_cidrs

  server         = data.hcloud_servers.gateway.servers[0]
  base_url       = "https://${var.sonar_hostname}"
  allowed_emails = [for email in var.allowed_emails : trimspace(email)]
  deploy_dir     = "/root/sonar-deploy"

  rendered = {
    "sonar.env" = templatefile("${path.module}/templates/sonar.env.tftpl", {
      google_client_id     = var.google_client_id
      google_client_secret = var.google_client_secret
      session_secret       = random_password.session_secret.result
      base_url             = local.base_url
      api_token            = random_password.api_token.result
    })
    "sonar.service" = templatefile("${path.module}/templates/sonar.service.tftpl", {})
    "sonar.conf" = templatefile("${path.module}/templates/sonar.conf.tftpl", {
      hostname = var.sonar_hostname
    })
  }

  install_args = concat(
    [var.sonar_repo_url, var.sonar_git_ref, var.uv_version, tostring(hcloud_volume.data.id), var.sonar_hostname],
    local.allowed_emails,
  )
  # Single-quote every argument so the remote shell passes it through verbatim.
  install_command = join(" ", concat(
    ["bash", "${local.deploy_dir}/install.sh"],
    [for arg in local.install_args : "'${replace(arg, "'", "'\\''")}'"],
  ))
}

resource "random_password" "session_secret" {
  length  = 48
  special = false
}

resource "random_password" "api_token" {
  length  = 48
  special = false
}

# The database lives here; it must outlive any redeploy of the app.
resource "hcloud_volume" "data" {
  name              = "sonar-data"
  size              = var.volume_size
  location          = local.server.location
  format            = "ext4"
  delete_protection = true

  lifecycle {
    prevent_destroy = true
  }
}

resource "hcloud_volume_attachment" "data" {
  volume_id = hcloud_volume.data.id
  server_id = local.server.id
  automount = false
}

resource "cloudflare_dns_record" "sonar" {
  zone_id = var.cloudflare_zone_id
  name    = var.sonar_hostname
  type    = "A"
  content = local.server.ipv4_address
  proxied = true
  ttl     = 1
}

# Sonar's own firewall on the Gateway VM: SSH from the deploying machine only. Hetzner combines the rules of all
# firewalls on a server, so this only adds access next to Gateway's firewall.
resource "hcloud_firewall" "sonar_ssh" {
  name = "sonar-ssh"

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    # Hide SSH source from CI logs to avoid exposing the owner's home IPv4.
    source_ips  = sensitive(local.ssh_allow_cidrs)
    description = "SSH for Sonar deploys"
  }

  apply_to {
    label_selector = var.server_label_selector
  }

  lifecycle {
    precondition {
      condition     = length(var.ssh_allow_cidrs) > 0 || can(regex("^[0-9]{1,3}(\\.[0-9]{1,3}){3}$", local.detected_ip))
      error_message = "Could not detect this machine's public IPv4 (got \"${local.detected_ip}\"). Set ssh_allow_cidrs."
    }
  }
}

resource "terraform_data" "install" {
  depends_on = [hcloud_volume_attachment.data, cloudflare_dns_record.sonar, hcloud_firewall.sonar_ssh]

  triggers_replace = {
    git_ref        = var.sonar_git_ref
    repo_url       = var.sonar_repo_url
    uv_version     = var.uv_version
    allowed_emails = local.allowed_emails
    volume_id      = hcloud_volume.data.id
    server_id      = local.server.id
    install_sh     = filesha256("${path.module}/files/install.sh")
    rendered       = { for name, content in local.rendered : name => sha256(content) }
  }

  connection {
    type        = "ssh"
    host        = local.server.ipv4_address
    user        = "root"
    private_key = file(pathexpand(var.ssh_private_key_path))
  }

  provisioner "remote-exec" {
    inline = ["install -d -m 0700 ${local.deploy_dir}"]
  }

  provisioner "file" {
    content     = local.rendered["sonar.env"]
    destination = "${local.deploy_dir}/sonar.env"
  }

  provisioner "file" {
    content     = local.rendered["sonar.service"]
    destination = "${local.deploy_dir}/sonar.service"
  }

  provisioner "file" {
    content     = local.rendered["sonar.conf"]
    destination = "${local.deploy_dir}/sonar.conf"
  }

  provisioner "file" {
    source      = "${path.module}/files/install.sh"
    destination = "${local.deploy_dir}/install.sh"
  }

  provisioner "remote-exec" {
    inline = [local.install_command]
  }
}
