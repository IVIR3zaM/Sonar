# Recurring income and CI deploys for the Gateway VM
status: RUNNING
created: 2026-10-05 · updated: 2026-10-05
goal: The payday forecast counts recurring non-salary income in its own dashboard card; Gateway, Sonar and Kita deploy side by side on the Gateway VM from local runs or GitHub Actions, with state in R2.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node

## Decisions

- D1 Salary exclusion: an income series whose typical day is within 7 days of the salary day, counted across the month end (min(|a−b|, 31−|a−b|) ≤ 7), is the salary and is never forecast as an extra inflow | confirmed
- D2 Income series are detected on the fly when the dashboard loads, from the transactions it already reads; they are not stored, not shown or edited on the Fixed payments page and not counted in fixed costs | confirmed
- D3 Window rule: every occurrence in [estimate date + 1, payday − 1] counts at the series' latest amount, except one already booked within 7 days (the same rule as `forecast.fixed_due`); worst and best both rise by the inflow total; expected = balance + inflows − due − expected Keep the lights on | confirmed
- D4 Display: a separate "Income before payday" card on the dashboard (`id="income-card"`) with a table (`id="inflows"`, one `data-row` per inflow with `data-field` `category`, `date` and `amount`) and its total (`id="inflow-total"`); the runway bar and its numbers include the inflow through the projection, with no bar segment of its own; with no inflow the card is absent | confirmed
- D5 Backend (all three repos): `backend "s3"` in each root's versions/providers file holds the fixed settings (its D14 key, region `auto`, path-style URLs, the skip_* checks R2 needs, `use_lockfile`); bucket and endpoint come from a gitignored `backend.hcl` next to it (tracked `backend.hcl.example`); credentials from AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY; CI writes the same backend.hcl from variables | confirmed
- D6 Locking: `use_lockfile = true` (terraform >= 1.10), checked by the owner's plans in N13; if R2 rejects the lock, drop it in all three and rely on the concurrency groups | confirmed
- D7 SSH access: each app owns a Hetzner firewall applied by label selector (`server_label_selector`, default `project=gateway`) that opens tcp/22 to the deployer's public IPv4. The IP is detected on every plan with the hashicorp/http provider (`api.ipify.org`, fallback `ipv4.icanhazip.com`), and `ssh_allow_cidrs` overrides it. Kita already has `hcloud_firewall.kita_ssh` (`../Kita/deploy/terraform/main.tf`, owner WIP); Sonar copies the pattern as `sonar-ssh`. Hetzner unions firewall rules, and the label survives Gateway's blue/green replacement. N13 checks that Gateway's plan shows no firewall_ids drift on `hcloud_server.v2ray` | confirmed
- D8 The repos are public, so Actions logs are public: Sonar's ALLOWED_EMAILS (a JSON list) is a secret, which masks it in logs | confirmed
- D9 Each repo has a GitHub environment `production`, limited to the main branch, that holds its deploy secrets and variables; test and validate jobs use no secrets | confirmed
- D10 Sonar workflow `.github/workflows/ci.yml`. Job `test` (pytest, ruff check, ruff format --check) runs on push (any branch), pull_request and workflow_dispatch. Job `deploy` needs test and runs on a push to main or a dispatch. Both check out the dispatch input `ref` (default `main`) or the pushed SHA, and deploy sets TF_VAR_sonar_git_ref to its full SHA. Deploy runs under the job-level concurrency group `deploy` (cancel-in-progress false) and stops before apply when `terraform state list` is empty | confirmed
- D11 Actions are pinned by full commit SHA with a `# vX.Y.Z` comment in all three workflows. Terraform is 1.16.5 everywhere and is read from a tracked `.tool-versions` where the repo tracks one (D20). uv is pinned to 0.8.17 and Node to 22 | confirmed
- D12 Only the owner handles credentials in all three repos: the R2 bucket and token, the state migrations, `gh secret set`/`gh variable set`, the PAT, pushes and dispatches. Pre-authorized for agents in Sonar, ../Kita and ../Gateway: `terraform init -backend=false`, `terraform validate`, `terraform fmt`, actionlint through uvx, read-only `gh api` calls for pin SHAs, and `gh secret list`/`gh variable list` (names only) | confirmed
- D13 Every push to main deploys once a workflow is on GitHub, so nothing is pushed in Sonar, Kita or Gateway before N13 and N14 (state migrated, settings set) and N12 (visual check) pass; the first pushes are the N15 gate | confirmed
- D14 State: one private R2 bucket with one key per project (`gateway/terraform.tfstate`, `sonar/terraform.tfstate`, `kita/terraform.tfstate`) and one R2 token reused by all three; the owner migrates each repo's local gitignored state with `terraform init -migrate-state` (Gateway's is ~60KB at `../Gateway/hetzner/terraform/terraform.tfstate`) | confirmed
- D15 Cross-repo nodes: the Kita and Gateway nodes live in this plan, and their executors work in ../Kita or ../Gateway with Write paths in that repo. They run that repo's checks (Kita `node --test`; Gateway `terraform fmt -check` and `terraform validate`). The orchestrator commits them with `git -C ../Kita` / `git -C ../Gateway`, because `plz commit` commits Sonar only. N02 comes first: the owner reviews and commits Kita's uncommitted firewall work and Gateway's uncommitted `hetzner/terraform/templates/stats.sh.tftpl` change; agents never commit the owner's WIP | confirmed
- D16 Kita workflow, same shape as D10/D11/D9. Job `test` runs `node --test` on Node 22 on push, PR and dispatch. Job `deploy` needs test and runs on a push to main or a dispatch (input `ref`), with TF_VAR_kita_git_ref = the resolved full SHA, the R2 backend from backend.hcl, environment `production`, concurrency group `deploy`, and a stop when the state list is empty. Kita's README is updated | confirmed
- D17 Gateway workflow for `hetzner/terraform`. It runs on a push to main touching `hetzner/**` or the workflow file, and on workflow_dispatch. A fmt/validate job runs first, then an apply job in `production` with concurrency group `deploy`. Every v2ray, user and token value is a secret; outputs that hold connection links or credentials are sensitive, and the workflow never prints outputs. Gateway's IP auto-detection in `local_env.tf` must work on runners. When the apply changed the server id, the workflow runs `gh workflow run` for Sonar's and Kita's deploy workflows with a fine-grained PAT secret (actions:write on Sonar and Kita only, created by the owner). The apps' install `triggers_replace` already includes the server id (`deploy/terraform/main.tf:99`), and Sonar's volume attachment follows `local.server.id` | confirmed
- D18 Coexistence: each deploy README says that during a Gateway replacement two servers briefly match the label, so an app deploy then fails its exactly-one-server postcondition safely and is re-run. `/etc/nginx/conf.d/sonar.conf` and `kita.conf` must pass `nginx -t` together with Gateway's config. N16 shows all three serving after a forced Gateway VM replacement and the automatic Sonar and Kita redeploys, and shows that a local `terraform apply` still works in each repo | confirmed
- D19 Drift fix: if N13 shows Gateway planning to detach the label-applied firewalls, set `ignore_remote_firewall_ids = true` on `hcloud_server.v2ray`; it is not ForceNew, and Kita's README (`../Kita/deploy/README.md:23`) already asks for it | confirmed
- D20 Terraform version: bump Gateway's `.tool-versions` from 1.5.1 to 1.16.5 and its `required_version` to `>= 1.10`, since S3 `endpoints` needs >= 1.6 and `use_lockfile` >= 1.10, and a 1.16 state can no longer be read by 1.5. Kita gitignores `.tool-versions` (owner WIP), so its workflow pins 1.16.5 directly | confirmed
- D21 Provider lock files are tracked in all three repos: Gateway's `.gitignore` drops `.terraform.lock.hcl` and N10 commits `hetzner/terraform/.terraform.lock.hcl`; Kita's untracked lock file goes into the owner's N02 commit; CI inits from them | confirmed
- D22 Gateway logs: Actions logs are public and a leaked gateway hostname can get it blocked. Secrets: HCLOUD_TOKEN, CLOUDFLARE_API_TOKEN, DOMAIN, SUBDOMAIN, WS_PATH, SSH_PRIVATE_KEY and DISPATCH_TOKEN (the PAT). Variables: SSH_PUBLIC_KEY plus any non-default `name`/`location`/`server_type`/`image`/`speedtest_mb` from the local tfvars. `ws_path`, `domain` and `subdomain` become `sensitive = true`; the outputs `fqdn`, `site_url` and `server_ipv4` become sensitive; both `local_file` contents are wrapped in `sensitive()`. A non-sensitive `server_id` output is read into a shell variable and never echoed | confirmed
- D23 App hostnames: Sonar's and Kita's hostnames live in the Gateway's zone, so SONAR_HOSTNAME, KITA_HOSTNAME and CLOUDFLARE_ZONE_ID are secrets (masked) rather than variables | confirmed
- D24 Concurrent installs: a Gateway replacement triggers both app deploys on a fresh VM at once, so Sonar's and Kita's `install.sh` run `cloud-init status --wait` and `apt-get -o DPkg::Lock::Timeout=300` (`deploy/terraform/files/install.sh:31-32`, `../Kita/deploy/terraform/files/install.sh:26-27`) | confirmed
- D25 Every CI and documented local terraform plan/apply uses `-lock-timeout=10m`, so a local and a CI run of the same project queue on the R2 lock instead of failing | confirmed
- D26 Gateway on runners: `local_env.tf` falls back to `https://ipv4.icanhazip.com` instead of `ifconfig.me`, which can answer IPv6. It picks the public key with a conditional instead of `coalesce`, which evaluates `file(...pub)` eagerly, so a runner with TF_VAR_ssh_public_key set never reads `~/.ssh` | confirmed
- D27 Gateway's dispatch has a boolean input `replace_server` (default false) that applies with `-replace=random_id.server_suffix -replace=hcloud_server.v2ray` (a new suffix avoids a name clash under create_before_destroy). N16 uses it to force the blue/green replacement, and it stays as a recovery tool | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/sonnet | 1 | 0 | DONE | |
| N02 | owner commits Kita and Gateway WIP | gate | N01 | -/- | 0 | 0 | TODO | |
| N03 | detect recurring income | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | forecast inflows before payday | exec | N03 | sonnet/sonnet | 0 | 0 | TODO | |
| N05 | income before payday card | exec | N04 | sonnet/sonnet | 0 | 0 | TODO | |
| N06 | Sonar terraform: R2 backend and SSH firewall | exec | N01 | sonnet/sonnet | 1 | 0 | VERIFYING | |
| N07 | Sonar CI workflow and deploy guide | exec | N06 | opus/sonnet | 0 | 0 | TODO | |
| N08 | Kita terraform: R2 backend and install lock wait | exec | N02 | sonnet/sonnet | 0 | 0 | TODO | |
| N09 | Kita CI workflow and deploy guide | exec | N07,N08 | sonnet/sonnet | 0 | 0 | TODO | |
| N10 | Gateway terraform: R2 backend, runner-safe and quiet | exec | N02 | opus/opus | 0 | 0 | TODO | |
| N11 | Gateway CI workflow, app redeploys and guide | exec | N07,N10 | opus/sonnet | 0 | 0 | TODO | |
| N12 | visual check of the dashboard | gate | N05 | -/sonnet | 0 | 0 | TODO | |
| N13 | owner R2, state migrations and drift check | gate | N06,N08,N10 | -/- | 0 | 0 | TODO | |
| N14 | owner GitHub environments, secrets and PAT | gate | N07,N09,N11,N13 | -/- | 0 | 0 | TODO | |
| N15 | owner first CI deploys of the apps | gate | N12,N14 | -/- | 0 | 0 | TODO | |
| N16 | owner Gateway replacement and coexistence | gate | N15 | -/- | 0 | 0 | TODO | |
| N17 | plan acceptance | check | N16 | -/opus | 0 | 0 | TODO | |
