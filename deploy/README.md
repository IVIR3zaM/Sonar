# Deploy Sonar to the Gateway VM

This guide takes you from an empty Google Cloud project to Sonar running behind Gateway's nginx on the existing Gateway VM at `https://sonar.example.com`. Replace `sonar.example.com`, `owner@example.com` and `<server_ipv4>` with your own values; none of the real ones belong in the repository.

Terraform (in `deploy/terraform`) looks up the Gateway VM, creates a protected data volume, adds a proxied Cloudflare A record and installs Sonar over SSH. It never manages the VM itself.

> **Note: `terraform validate` was not run.** When this module was written the provider registry (`registry.terraform.io`) was unreachable from the build sandbox, so only `terraform fmt -check`, `bash -n` and offline template rendering ran. Run `terraform init && terraform validate` in `deploy/terraform` before the first apply and fix anything it reports.

## Prerequisites

- terraform >= 1.6.
- A Hetzner API token with read/write access to the Gateway project.
- A Cloudflare API token with Zone DNS Edit on the zone, plus the zone ID.
- An SSH private key that logs in as root on the Gateway VM (default `~/.ssh/id_ed25519`, see `ssh_private_key_path`).
- You run terraform from an IP inside a CIDR that Gateway's Hetzner firewall allows for SSH. Sonar does not change that firewall.
- The zone's SSL/TLS mode is set to Full, not Full (strict): the origin certificate Sonar installs is self-signed. Sonar changes no zone-wide setting, so set the mode yourself in Cloudflare.
- The Gateway VM carries the Hetzner label `project=gateway` and it is the only server matching that selector (the default `server_label_selector`). Apply fails if the selector matches zero or several servers.

## 1. Google OAuth setup

Start from an empty Google Cloud project.

1. In the Google Cloud console create a project (for example `sonar`).
2. Open Google Auth Platform (APIs & Services, OAuth consent screen) and configure the consent screen:
   - User type: External.
   - Scopes: only `openid`, `email` and `profile`.
   - While the app is in Testing, add every email you will allow as a test user (for example `owner@example.com`). Alternatively publish the app.
3. Create an OAuth client (Clients, Create client):
   - Application type: Web application.
   - Authorized redirect URIs, exactly these two (substitute your real host in the first):
     - `https://sonar.example.com/auth/callback`
     - `http://127.0.0.1:8000/auth/callback`
4. Copy the client ID and client secret.
5. Create your variables file and put the client ID and secret there and, for local runs, in `.env`:

   ```bash
   cp deploy/terraform/terraform.tfvars.example deploy/terraform/terraform.tfvars
   ```

   `terraform.tfvars` and `.env` are both gitignored. Never put the client ID or secret anywhere else in the repository.

## 2. Check sign-in locally

Before deploying, prove the OAuth client works on your machine. Use a temp database, never `data/sonar.db`.

```bash
cp .env.example .env
```

In `.env`, fill in:

- `SONAR_GOOGLE_CLIENT_ID` and `SONAR_GOOGLE_CLIENT_SECRET`: from step 4.
- `SONAR_SESSION_SECRET`: the output of `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
- `SONAR_BASE_URL`: `http://127.0.0.1:8000` (127.0.0.1, not localhost: it must match the redirect URI).
- `SONAR_ALLOWED_EMAILS`: `owner@example.com`.
- `SONAR_DB_PATH`: a temp file, for example `/tmp/sonar-check/sonar.db`.

Then start it. `run.sh` loads `.env`, syncs the allowed emails into the database and starts Sonar:

```bash
./run.sh
```

Open <http://127.0.0.1:8000> and check:

- Signing in with `owner@example.com` reaches the dashboard.
- Signing in with any other Google account shows the not-allowed page.
- Logging out returns to the sign-in page.

Stop the app. Afterwards empty the sign-in variables in `.env` and restore `SONAR_DB_PATH=data/sonar.db`.

## 3. Patch Gateway's nginx

Sonar's nginx server block is installed as `/etc/nginx/conf.d/sonar.conf`, so Gateway's nginx must include that directory. In the Gateway repository, open `hetzner/terraform/templates/nginx.conf.tftpl` and add this one line inside the `http { }` block:

```nginx
include /etc/nginx/conf.d/*.conf;
```

Re-apply Gateway, then check that its `/ping` still answers.

If the line is missing, Sonar's install stops with an error that names `deploy/README.md`; add the line, re-apply Gateway and apply Sonar again.

## 4. Deploy with terraform

1. Merge `claude/youthful-thompson-0snams` into `main` on github.com/IVIR3zaM/Sonar and push `main`. The VM clones the public repository without credentials, so the commit must be on GitHub.
2. Get the full 40-character SHA of that main commit and set it as `sonar_git_ref`:

   ```bash
   git rev-parse origin/main
   ```

3. Fill in `deploy/terraform/terraform.tfvars`. Every variable:

   | Variable | Meaning | Default |
   |---|---|---|
   | `hcloud_token` | Hetzner Cloud API token with read/write access to the Gateway project (sensitive). | required |
   | `cloudflare_api_token` | Cloudflare API token allowed to edit DNS records in the zone (sensitive). | required |
   | `cloudflare_zone_id` | Cloudflare zone ID of the domain that holds `sonar_hostname`. | required |
   | `sonar_hostname` | Public FQDN of Sonar, lowercase, for example `sonar.example.com`. | required |
   | `google_client_id` | Client ID of the Google OAuth client. | required |
   | `google_client_secret` | Client secret of the Google OAuth client (sensitive). | required |
   | `allowed_emails` | Every email allowed to sign in, at least one; each apply replaces the access list with exactly these. | required |
   | `sonar_git_ref` | Full 40-character commit SHA on `main` to deploy. | required |
   | `sonar_repo_url` | Public Git URL of Sonar, cloned without credentials. | `https://github.com/IVIR3zaM/Sonar.git` |
   | `uv_version` | uv version installed on the VM. | `0.8.17` |
   | `volume_size` | Size in GB of the volume that holds the SQLite database. | `10` |
   | `server_label_selector` | Hetzner label selector that matches exactly one server: the Gateway VM. | `project=gateway` |
   | `ssh_private_key_path` | Private key that logs in as root on the Gateway VM. | `~/.ssh/id_ed25519` |

4. Apply:

   ```bash
   cd deploy/terraform
   terraform init
   terraform validate
   terraform apply
   ```

Apply creates:

- the `sonar-data` volume, protected from deletion (`delete_protection` and `prevent_destroy`), and its attachment to the Gateway VM;
- a proxied Cloudflare A record for `sonar_hostname` pointing at the VM;
- the install over SSH as root: system user, mounted volume, uv, the app checked out at `sonar_git_ref`, the systemd unit, the nginx conf and a self-signed origin certificate, then an nginx reload, a readiness wait (up to 60 seconds on `/auth/login`) and an email sync that writes `allowed_emails` into the database.

The app listens on `127.0.0.1:8000` and its database is `/var/lib/sonar/sonar.db` on the volume.

Outputs:

| Output | Meaning |
|---|---|
| `sonar_url` | Public address of Sonar. |
| `server_ipv4` | Public IPv4 of the Gateway VM. |
| `volume_id` | ID of the protected volume that holds the database. |
| `api_token` | Bearer token for `/api/*` (sensitive). |

For scripts and Claude Code, read the token with `terraform output -raw api_token` and send it as `Authorization: Bearer <token>` (this is `SONAR_API_TOKEN`):

```bash
SONAR_API_TOKEN="$(terraform output -raw api_token)"
curl -s -H "Authorization: Bearer $SONAR_API_TOKEN" "$(terraform output -raw sonar_url)/api/categories"
```

## 5. Upload your database once

A fresh deploy starts with an empty database. To bring your local data across:

1. Stop the local app so the file is not being written.
2. On the VM, stop Sonar:

   ```bash
   ssh root@<server_ipv4> systemctl stop sonar
   ```

3. Copy the database. Use the IP, because the proxied hostname carries no SSH:

   ```bash
   scp data/sonar.db root@<server_ipv4>:/var/lib/sonar/sonar.db
   ```

4. Fix ownership and start Sonar:

   ```bash
   ssh root@<server_ipv4> 'chown sonar:sonar /var/lib/sonar/sonar.db && systemctl start sonar'
   ```

5. The upload replaced the access list with your local one, so restore it (list every allowed email):

   ```bash
   ssh root@<server_ipv4> 'runuser -u sonar -- /opt/sonar/.venv/bin/sonar sync-emails owner@example.com --db /var/lib/sonar/sonar.db'
   ```

6. Check from your machine:
   - Signed-out `https://sonar.example.com/` lands on the sign-in page.
   - The API answers 200 with the bearer token and 401 without it:

     ```bash
     curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $SONAR_API_TOKEN" https://sonar.example.com/api/categories   # 200
     curl -s -o /dev/null -w '%{http_code}\n' https://sonar.example.com/api/categories                                              # 401
     ```

## Operations

- **Upgrade:** merge to `main`, push, set `sonar_git_ref` to the new full SHA and run `terraform apply`.
- **Access list:** `allowed_emails` in `terraform.tfvars` is authoritative. Every apply replaces the access list with exactly those emails, so removing one locks it out on its next request. Add the person as a Google test user too while the app is in Testing.
- **Gateway redeploy:** if redeploying Gateway replaces the VM, re-run Sonar's `terraform apply`. The data survives on the volume, which is reattached and remounted.
- **Never destroy the volume.** It has `prevent_destroy` and Hetzner delete protection, because the SQLite database lives on it.
- **Secrets:** `terraform.tfvars` and `terraform.tfstate` hold secrets (state is local). Keep them on your machine, back them up privately and never commit them.
- **Logs:** `ssh root@<server_ipv4> journalctl -u sonar`.
