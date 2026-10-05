# Deploy Sonar to the Gateway VM

This guide takes you from an empty Google Cloud project to Sonar running behind Gateway's nginx on the existing Gateway VM at `https://sonar.example.com`. Replace `sonar.example.com`, `owner@example.com` and `<server_ipv4>` with your own values; none of the real ones belong in the repository.

Terraform (in `deploy/terraform`) looks up the Gateway VM, creates a protected data volume, adds a proxied Cloudflare A record, opens SSH through Sonar's own `sonar-ssh` firewall and installs Sonar over SSH. It never manages the VM itself. Its state lives in Cloudflare R2. You deploy either from your machine or from GitHub Actions (`.github/workflows/ci.yml`); both use the same state and lock.

## Prerequisites

- terraform 1.16.5 (the version CI pins; the module needs >= 1.10 for the R2 lock file).
- A Cloudflare R2 bucket and an R2 API token for the state (see [R2 state backend](#r2-state-backend)).
- A Hetzner API token with read/write access to the Gateway project.
- A Cloudflare API token with Zone DNS Edit on the zone, plus the zone ID.
- An SSH private key that logs in as root on the Gateway VM (default `~/.ssh/id_ed25519`, see `ssh_private_key_path`).
- SSH access comes from Sonar's own Hetzner firewall `sonar-ssh`, attached to the Gateway VM next to Gateway's firewall. It opens port 22 to `ssh_allow_cidrs`; by default that is the public IPv4 of the machine running terraform, detected on every plan, so a local run and a CI runner both get in. Gateway's firewall is never changed.
- The zone's SSL/TLS mode is set to Full, not Full (strict): the origin certificate Sonar installs is self-signed. Sonar changes no zone-wide setting, so set the mode yourself in Cloudflare.
- The Gateway VM carries the Hetzner label `project=gateway` and it is the only server matching that selector (the default `server_label_selector`). Apply fails if the selector matches zero or several servers.

## R2 state backend

Gateway, Sonar and Kita share one private R2 bucket and one R2 API token (Object Read & Write on that bucket). Each project has its own key; Sonar's is `sonar/terraform.tfstate` (set in `versions.tf`). Terraform locks the state with a lock file next to it in the bucket.

1. In Cloudflare, create the private bucket once (or reuse the one Gateway already uses) and an R2 API token scoped to it. Note the account ID, the bucket name, and the token's access key ID and secret access key.
2. Create the backend config (gitignored), fill in the bucket, account ID and R2 credentials, then restrict it:

   ```bash
   cd deploy/terraform
   cp backend.hcl.example backend.hcl
   # Edit backend.hcl: fill in bucket, account ID, access_key and secret_key
   chmod 600 backend.hcl
   ```

3. The R2 credentials in `backend.hcl` take precedence over any `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` variables or `AWS_PROFILE` in your shell, so nothing is exported. This means other AWS profiles and `~/.aws` stay untouched, and Sonar's terraform never touches your other AWS accounts.

4. One time only, if you already have a terraform root from an earlier deploy, reinitialize it:

   ```bash
   terraform init -reconfigure -backend-config=backend.hcl
   ```

   If you also have a local `terraform.tfstate` from before the R2 backend was set up, pass `-migrate-state` instead of `-reconfigure`:

   ```bash
   terraform init -migrate-state -backend-config=backend.hcl
   ```

   Answer yes to move the state to R2. Afterwards `terraform state list` must show the volume, its attachment, the DNS record and the install; then keep the old local state files only as a private backup. On a first-ever deploy, just run `terraform init -backend-config=backend.hcl`.

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

## 4. Deploy from your machine

1. Push the commit you want to deploy to `main` on GitHub. The VM clones the public repository without credentials, so the commit must be on GitHub.
2. Get the full 40-character SHA of the current main commit and set it as `sonar_git_ref`:

   ```bash
   git fetch origin
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
   | `ssh_allow_cidrs` | CIDRs the `sonar-ssh` firewall opens port 22 to. Empty means this machine's public IPv4, detected on every plan. | `[]` |

4. With `backend.hcl` filled in, apply:

   ```bash
   cd deploy/terraform
   terraform init -backend-config=backend.hcl
   terraform validate
   terraform plan -lock-timeout=10m
   terraform apply -lock-timeout=10m
   ```

   `-lock-timeout=10m` makes a run wait for the R2 lock when another one (local or CI) holds it, instead of failing at once.

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

## GitHub Actions

`.github/workflows/ci.yml` (workflow `CI`) has two jobs:

- `test` runs on every push to any branch, every pull request and every manual dispatch: `uv sync --locked`, `pytest`, `ruff check` and `ruff format --check`. It uses no environment and no secret.
- `deploy` needs `test` and runs only after a push to `main` or a manual dispatch. It applies `deploy/terraform` on the R2 backend.

What triggers a deploy:

- **Push to main:** the pushed commit is tested and deployed.
- **Dispatch:** Actions, CI, Run workflow, with input `ref` (a branch, tag or SHA; default `main`). Both jobs check out that ref, and `deploy` resolves it to the full commit SHA it hands terraform as `sonar_git_ref`, so the VM always installs one exact commit. The ref must be pushed to GitHub. From the command line: `gh workflow run ci.yml -f ref=main`.

Set up once, in the repository settings:

1. Create the environment `production` and limit its deployment branches to `main`. The `deploy` job runs in it.
2. Add these secrets and variables to the `production` environment:

   | Name | Kind | Terraform variable or use |
   |---|---|---|
   | `HCLOUD_TOKEN` | secret | `hcloud_token`; also lists the Gateway VM to mask its IP |
   | `CLOUDFLARE_API_TOKEN` | secret | `cloudflare_api_token` |
   | `CLOUDFLARE_ZONE_ID` | secret | `cloudflare_zone_id` |
   | `SONAR_HOSTNAME` | secret | `sonar_hostname` |
   | `GOOGLE_CLIENT_ID` | variable | `google_client_id` |
   | `GOOGLE_CLIENT_SECRET` | secret | `google_client_secret` |
   | `ALLOWED_EMAILS` | secret | `allowed_emails`, as a JSON list, for example `["owner@example.com"]` |
   | `SSH_PRIVATE_KEY` | secret | written to a mode-600 file in the runner's temp dir; its path is `ssh_private_key_path` |
   | `R2_ACCESS_KEY_ID` | secret | `AWS_ACCESS_KEY_ID` for the R2 backend |
   | `R2_SECRET_ACCESS_KEY` | secret | `AWS_SECRET_ACCESS_KEY` for the R2 backend |
   | `R2_ACCOUNT_ID` | variable | endpoint `https://<account-id>.r2.cloudflarestorage.com` in the generated `backend.hcl` |
   | `R2_BUCKET` | variable | `bucket` in the generated `backend.hcl` |

   `ssh_allow_cidrs` is not set in CI, so `sonar-ssh` opens port 22 to the runner's own IPv4 for that run.

How the deploy job behaves:

- **One at a time:** every deploy joins the `deploy` concurrency queue and waits; none is cancelled, because an apply cut short could leave the R2 lock held.
- **Empty-state guard:** after `terraform init` the job checks `terraform state list`. If the state is empty (not migrated to R2, or the wrong bucket or key) it fails before apply, because an apply would create a second data volume.
- **Lock:** apply runs with `-lock-timeout=10m`, so it waits for a local run that holds the lock.
- **Logs are public.** The repository is public, so anyone can read the workflow logs. The job masks every allowed email and the Gateway VM's IPv4 before any terraform call, runs terraform without the output wrapper and never runs `terraform output`. Read outputs such as `api_token` from your machine instead.

## Coexistence with Gateway and Kita

Sonar shares the Gateway VM with Gateway and Kita, and the bucket with both.

- **Gateway replaces the VM:** while Gateway swaps the VM, two servers briefly carry `project=gateway`. A Sonar deploy in that window fails its exactly-one-server check before changing anything; re-run it once the old server is gone.
- **Gateway redeploys Sonar:** after Gateway's workflow replaces the VM, it dispatches this workflow (`ci.yml` with `ref=main`), so Sonar is reinstalled on the new VM and its volume reattached without you doing anything.
- **nginx:** Sonar's `sonar.conf` sits in `/etc/nginx/conf.d/` next to Kita's, and Gateway's `nginx.conf` includes them all. Together they must pass `nginx -t`; the install stops before reloading nginx if they don't. Keep server names and listen options compatible across the three projects.
- **Lock:** a local apply and a CI run use the same R2 state and lock, so whichever starts second waits (up to `-lock-timeout=10m`).

## Operations

- **Upgrade:** push to `main`. CI tests the commit and deploys it. For a local apply instead, set `sonar_git_ref` to the current main SHA first (`git rev-parse origin/main`); an older SHA would roll Sonar back.
- **Access list:** `allowed_emails` (in `terraform.tfvars` locally, the `ALLOWED_EMAILS` secret in CI) is authoritative. Every apply replaces the access list with exactly those emails, so removing one locks it out on its next request. Keep the two in sync, and add the person as a Google test user too while the app is in Testing.
- **Gateway redeploy:** if redeploying Gateway replaces the VM, Gateway's workflow dispatches Sonar's deploy; if it doesn't, run `gh workflow run ci.yml -f ref=main`. The data survives on the volume, which is reattached and remounted.
- **Never destroy the volume.** It has `prevent_destroy` and Hetzner delete protection, because the SQLite database lives on it.
- **Secrets:** state lives in R2, not on your machine, and holds secrets; keep the bucket private. `backend.hcl` holds your R2 credentials; terraform copies them into the gitignored `.terraform/` directory and into any saved `-out` plan files. Never share `.terraform/`, plan files, `terraform.tfvars`, or your SSH key. All four are gitignored; never commit them.
- **Logs:** `ssh root@<server_ipv4> journalctl -u sonar`.
