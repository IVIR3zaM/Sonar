# Google login and Hetzner deploy
status: RUNNING
created: 2026-10-02 · updated: 2026-10-02
goal: Sonar runs on a real domain behind Google login with a DB allow-list, deployed by terraform onto the Gateway VM, with one instruction file and loans drafted from fixed payments
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: per-node
budgets: 2 tries per brief · 2 replans per node

## Decisions

- D1 N02 AGENTS.md takes CLAUDE.md's full content above the untouched planzilla:begin/end block; CLAUDE.md becomes the single line `@AGENTS.md`; `planzilla install` only rewrites that marked block of AGENTS.md and never writes CLAUDE.md (.planzilla/lib/planzilla/commands/install.py:175) | confirmed
- D2 N02 The Uncategorized export's first line becomes `Categorization request: follow the Categorization workflow in AGENTS.md.` (src/sonar/categorization/export.py:21, SPEC §5) with a SPEC §13 amendment | confirmed
- D3 Auth is on only when SONAR_GOOGLE_CLIENT_ID, SONAR_GOOGLE_CLIENT_SECRET, SONAR_SESSION_SECRET and SONAR_BASE_URL are all set; none set = today's app; some but not all = `sonar` exits with an error naming the missing ones | confirmed
- D4 OIDC through authlib's Starlette client (Google discovery, state, nonce, id_token checks) on Starlette's SessionMiddleware (itsdangerous-signed cookie); authlib, itsdangerous and httpx become runtime deps; tests swap the Google client for a fake | confirmed
- D5 The session cookie holds only the email; 14-day max age, SameSite=Lax (cross-site form POSTs carry no cookie), Secure when SONAR_BASE_URL is https; the allow-list is checked on every request, so a revoke takes effect at once | confirmed
- D6 Routes: GET /auth/login (sign-in page with a Google button, also where logout lands), GET /auth/google (redirect to Google), GET /auth/callback (redirect URI = SONAR_BASE_URL + /auth/callback), GET /auth/logout; no session: pages 302 to /auth/login, /api/* 401 JSON; /static/* stays public; signed in but unlisted or unverified email: 403 "not allowed" page with logout | confirmed
- D7 Runtime env: SONAR_DB_PATH (default data/sonar.db) and SONAR_PORT (default 8000); host stays 127.0.0.1; uvicorn trusts X-Forwarded-* from 127.0.0.1 only; the email commands take --db defaulting to SONAR_DB_PATH | confirmed
- D8 SONAR_API_TOKEN is optional; when set, /api/* (and nothing else) also accepts `Authorization: Bearer <token>`, compared with hmac.compare_digest; terraform generates it with random_password and exposes it as a sensitive output | confirmed
- D9 `sonar sync-emails` needs at least one email and terraform's `allowed_emails` validates length >= 1, so no apply can lock everyone out; emails are trimmed, lowercased and must contain exactly one @ | confirmed
- D10 Migrations are numbered 0007_allowed_emails.sql, 0008_category_debt.sql, 0009_debt_drafts.sql | confirmed
- D11 The debt flag is allowed only on `fixed` categories (friendly 400 otherwise); 0008 flags the seeded "Loans & Installments" category if it still exists | confirmed
- D12 The flag survives edits: PUT /api/categories without `debt` keeps the current value, POST defaults it to false, and `import-categories` keeps the flag of each category whose name survives | confirmed
- D13 Drafts come only from active detected recurring payments (detection key set) in debt-flagged categories, one per key in a new debt_drafts table; an open draft holds no hand data and is deleted when its payment stops qualifying; completing it creates an ordinary installment or loan through the existing model and marks the draft completed, so it never returns, even if that debt is deleted later | confirmed
- D14 Draft prefill: payment name, latest amount as rate, earliest matching debit as first payment date, interval from the payment's schedule; match rule = mandate + ref for `mandate:` keys, else counterparty = the latest matching debit's counterparty; debts keep their two match fields (no debts table rebuild) | confirmed
- D15 No CSS build on the VM: the committed sonar.css is the build output and SPEC §12 requires starting without Tailwind | confirmed
- D16 Terraform finds the Gateway VM with the hcloud_servers data source by a label selector variable (default `project=gateway`, which Gateway sets) and fails with a clear message unless exactly one server matches | confirmed
- D17 Gateway's Hetzner firewall and Cloudflare zone settings stay untouched: SSH provisioning works only from a CIDR Gateway's firewall allows, and Sonar relies on the zone's SSL Full mode; both are documented, Sonar adds only its proxied A record | confirmed
- D18 VM layout: system user `sonar`, checkout of var.sonar_git_ref in /opt/sonar, pinned uv, `uv sync --frozen --no-dev`, env file /etc/sonar/sonar.env (0600), ext4 volume mounted at /var/lib/sonar via fstab by-id, DB /var/lib/sonar/sonar.db, app on 127.0.0.1:8000 (Gateway's v2ray uses 10000), /etc/nginx/conf.d/sonar.conf with its own self-signed origin cert | confirmed
- D19 Terraform state stays local; terraform.tfvars, .terraform/ and *.tfstate* are gitignored (state holds secrets); only terraform.tfvars.example with example.com placeholders is committed | confirmed
- D20 N01 Preflight installs a pinned terraform binary outside the repo from releases.hashicorp.com and checks the provider registry; if either is unreachable, N09 swaps its fmt/validate criteria for review and deploy/README.md records the gap | confirmed
- D21 Pre-authorize mid-run: `uv add` of authlib, itsdangerous and httpx with the uv.lock change; migrations 0007-0009; edits to SPEC.md (§0 and §13), AGENTS.md, CLAUDE.md, README.md and .plan/config.md's comment; terraform init and validate without credentials (never plan or apply) | confirmed
- D22 N13 Agents push only claude/youthful-thompson-0snams (D24); the owner merges it into main on github.com/IVIR3zaM/Sonar and pushes main before N13, sets sonar_git_ref to that main commit, patches Gateway's nginx.conf template, fills terraform.tfvars and runs terraform apply; no agent touches real credentials, the Gateway repo or the VM | confirmed
- D23 N11 The owner does the Google Cloud setup from deploy/README.md; the client id and secret live only in gitignored terraform.tfvars (and a shell env for a local check) | confirmed
- D24 Push per node: each node commit is pushed to origin claude/youthful-thompson-0snams, the checked-out branch of this cloud session (plan push: per-node); N01 proves push rights to it; nothing is pushed to main by an agent | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/sonnet | 1 | 0 | DONE | |
| N02 | AGENTS.md as the single instruction source | exec | N01 | sonnet/sonnet | 1 | 1 | DONE | |
| N03 | allowed emails store and CLI | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | Google login and sessions | exec | N03 | opus/opus | 0 | 0 | TODO | |
| N05 | API bearer token and auth docs | exec | N04 | sonnet/sonnet | 0 | 0 | TODO | |
| N06 | category debt flag | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N07 | draft debts from recurring payments | exec | N06 | opus/opus | 0 | 0 | TODO | |
| N08 | needs-details debts on the debts page | exec | N07 | sonnet/sonnet | 0 | 0 | TODO | |
| N09 | terraform deploy module | exec | N05 | opus/opus | 0 | 0 | TODO | |
| N10 | Google setup and deploy guide | exec | N09 | sonnet/sonnet | 0 | 0 | TODO | |
| N11 | owner Google OAuth setup | gate | N10 | -/- | 0 | 0 | TODO | |
| N12 | visual check | check | N08 | -/sonnet | 0 | 0 | TODO | |
| N13 | owner deploy to the Gateway VM | gate | N11,N12 | -/- | 0 | 0 | TODO | |
| N14 | plan acceptance | check | N13 | -/opus | 0 | 0 | TODO | |
