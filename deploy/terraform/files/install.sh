#!/usr/bin/env bash
# Installs or upgrades Sonar on the Gateway VM. Run as root by Terraform; safe to re-run.
# Usage: install.sh REPO_URL GIT_REF UV_VERSION VOLUME_ID HOSTNAME EMAIL...
set -euo pipefail

if [[ $# -lt 6 ]]; then
  echo "usage: $0 REPO_URL GIT_REF UV_VERSION VOLUME_ID HOSTNAME EMAIL..." >&2
  exit 2
fi

repo_url=$1
git_ref=$2
uv_version=$3
volume_id=$4
hostname=$5
shift 5
allowed_emails=("$@")

deploy_dir=$(cd "$(dirname "$0")" && pwd)
app_dir=/opt/sonar
data_dir=/var/lib/sonar
sonar_home=/home/sonar
volume_device=/dev/disk/by-id/scsi-0HC_Volume_${volume_id}

as_sonar() {
  (cd / && runuser -u sonar -- env HOME="$sonar_home" PATH=/usr/local/bin:/usr/bin:/bin "$@")
}

install_packages() {
  export DEBIAN_FRONTEND=noninteractive
  # A fresh VM may still be running cloud-init's own apt install; wait for it, and for the dpkg lock, instead of
  # failing. cloud-init exits 2 on recoverable errors and may be absent, neither of which should stop the install.
  cloud-init status --wait >/dev/null 2>&1 || true
  apt-get -o DPkg::Lock::Timeout=300 update -q
  apt-get -o DPkg::Lock::Timeout=300 install -y -q git nginx openssl curl
}

create_user() {
  if ! id -u sonar >/dev/null 2>&1; then
    useradd --system --create-home --home-dir "$sonar_home" --shell /usr/sbin/nologin sonar
  fi
}

# Hetzner formats the volume when Terraform creates it; this only mounts it.
mount_volume() {
  for _ in $(seq 30); do
    [[ -e $volume_device ]] && break
    sleep 1
  done
  if [[ ! -e $volume_device ]]; then
    echo "Volume device $volume_device did not appear." >&2
    exit 1
  fi
  mkdir -p "$data_dir"
  if ! grep -qs "^$volume_device " /etc/fstab; then
    echo "$volume_device $data_dir ext4 discard,nofail,defaults 0 0" >>/etc/fstab
    systemctl daemon-reload
  fi
  if ! mountpoint -q "$data_dir"; then
    mount "$data_dir"
  fi
  chown sonar:sonar "$data_dir"
}

install_uv() {
  if [[ "$(/usr/local/bin/uv --version 2>/dev/null || true)" != "uv $uv_version"* ]]; then
    curl -LsSf "https://astral.sh/uv/$uv_version/install.sh" | env UV_UNMANAGED_INSTALL=/usr/local/bin sh
  fi
}

checkout_app() {
  if [[ ! -d $app_dir/.git ]]; then
    install -d -o sonar -g sonar "$app_dir"
    as_sonar git clone --quiet "$repo_url" "$app_dir"
  else
    as_sonar git -C "$app_dir" fetch --quiet --prune origin
  fi
  as_sonar git -C "$app_dir" checkout --quiet --detach "$git_ref"
  as_sonar uv --directory "$app_dir" sync --frozen --no-dev
}

install_config() {
  install -d -m 0755 /etc/sonar
  install -m 0600 -o root -g root "$deploy_dir/sonar.env" /etc/sonar/sonar.env
  install -d -m 0700 /etc/sonar/tls
  # Cloudflare (Full mode) accepts a self-signed origin certificate.
  if [[ ! -f /etc/sonar/tls/origin.crt ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$hostname" \
      -keyout /etc/sonar/tls/origin.key -out /etc/sonar/tls/origin.crt
    chmod 0600 /etc/sonar/tls/origin.key
  fi
  install -m 0644 "$deploy_dir/sonar.service" /etc/systemd/system/sonar.service
  install -m 0644 "$deploy_dir/sonar.conf" /etc/nginx/conf.d/sonar.conf
  systemctl daemon-reload
  systemctl enable sonar.service
}

reload_nginx() {
  local config_dump
  if ! config_dump=$(nginx -T 2>&1); then
    echo "$config_dump" >&2
    exit 1
  fi
  if ! grep -qF "# configuration file /etc/nginx/conf.d/sonar.conf:" <<<"$config_dump"; then
    echo "nginx does not load /etc/nginx/conf.d/sonar.conf; add the include described in deploy/README.md." >&2
    exit 1
  fi
  nginx -t
  systemctl reload nginx
}

wait_until_ready() {
  for _ in $(seq 60); do
    if [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/auth/login || true)" == 200 ]]; then
      return
    fi
    sleep 1
  done
  echo "Sonar did not answer on http://127.0.0.1:8000/auth/login within 60s; see journalctl -u sonar." >&2
  exit 1
}

install_packages
create_user
mount_volume
install_uv
checkout_app
install_config
reload_nginx
systemctl restart sonar.service
wait_until_ready
as_sonar "$app_dir/.venv/bin/sonar" sync-emails "${allowed_emails[@]}" --db "$data_dir/sonar.db"
