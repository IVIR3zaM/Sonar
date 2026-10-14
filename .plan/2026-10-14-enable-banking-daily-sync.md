# Enable Banking daily sync
status: WAITING
created: 2026-10-14 · updated: 2026-10-14
goal: Every morning Sonar fetches the Deutsche Bank Girokonto's booked transactions and balance from Enable Banking, and the owner renews the ~180-day consent from a banner or Settings in a few clicks.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: Today the Girokonto data reaches Sonar only when the owner downloads a CSV and uploads it. Sonar will pull it itself: a timer on the server runs `sonar bank-sync` at 06:30 Berlin time. The sync fetches the booked transactions since the last sync and today's balance from Enable Banking, using the owner's own linked account in restricted mode and requests signed with the app's private key. The rows go through the existing import pipeline, so rules, recurring detection and the forecast work on them as they do on CSV rows. The owner connects once from Settings and reconnects the same way when the bank consent runs out. A banner on every page warns 14 days before the consent ends, when it has ended and after a failed sync.

In scope: a SPEC §13 Bank sync amendment that replaces the "don't build it" line at SPEC.md:10; a `banking` feature package (env settings, the JWT-signed HTTP client, pure payload mapping, consent and banner rules, store, sync service); one migration for the connection state; the Connect/Reconnect flow with a state-checked callback; the `sonar bank-sync` command; a Settings "Bank connection" card with Sync now; the banner; `/api/bank` for parity; the systemd service and timer in the Terraform install, the CI secrets and the deploy README; an owner-run comparison of API rows with the stored CSV rows that decides how API and CSV rows overlap.

Out of scope: email or push notifications, other banks or accounts, payments, pending transactions, more than one bank connection, changes to the CSV importers beyond the overlap rule, and committing any real bank data.

Constraints: AGENTS.md rules: strict TDD, KISS, functional core with `today`/`now` as parameters, integer cents, `store.py`/`service.py` the only DB access, a new package only with a SPEC feature, migrations additive only, `tests/test_architecture.py` green, page tests on ids through `tests/html.py`, `sonar.css` rebuilt and committed. Secrets only from env, never printed, logged, rendered or stored in tracked files. OWASP: state parameter on the redirect, callback behind sign-in, private key never under a served path, TLS verification on, generic error text. The app starts with one command and works unchanged when Enable Banking is not configured. Decisions D1-D15.

Definition of done: verify passes; the visual gate passes for the Settings card and the banner at desktop and 375px, light and dark; on prod the owner connects, runs a sync, sees new transactions and today's balance, and `systemctl list-timers` lists the timer; the final check passes SPEC §11 and §12.

## Decisions

- D1 Package: a new `src/sonar/banking/` behind the new SPEC §13 Bank sync feature, holding `settings.py` (env, pure), `client.py` (HTTP and JWT shell), `consent.py` (pure consent and banner rules), `mapping.py` (pure payload → `ParsedTransaction`/`ParsedBalance`), `store.py` and `service.py`. Routes go in `web/pages/bank.py` and `web/api/bank.py` | confirmed
- D2 Config: env `SONAR_ENABLE_BANKING_APP_ID` and `SONAR_ENABLE_BANKING_KEY_PATH`; an empty value counts as unset. With both unset the feature is off: no bank routes (404), no Settings card, no banner, and `bank-sync` prints "Bank sync is not configured." and exits 0. With only one set, `sonar` refuses to start and names the missing one, as sign-in does (src/sonar/auth/settings.py:35-50). The key file must be readable and resolve outside `src/sonar/web/static/`, else `sonar` refuses to start; its contents are never printed. Redirect URL = `SONAR_BASE_URL`, else `http://127.0.0.1:<SONAR_PORT>`, plus `/bank/callback`. ASPSP = name "Deutsche Bank", country "DE" (N03 confirms the exact name) | confirmed
- D3 Client: base `https://api.enablebanking.com`; each request carries `Authorization: Bearer <JWT>`. The JWT is RS256, signed with `authlib.jose` (already a dependency, so no new package), with header `kid` = app id and claims `iss` "enablebanking.com", `aud` "api.enablebanking.com", `iat` now and `exp` now + 1 h. Calls: GET `/aspsps?country=DE`; POST `/auth`; POST `/sessions`; GET `/accounts/{uid}/transactions` with `date_from`, `date_to` and `transaction_status=BOOK`, following `continuation_key`; GET `/accounts/{uid}/balances`. httpx uses a 30 s timeout with TLS verification on. A non-2xx answer or a transport error raises `BankApiError(status, message)`: at most 200 characters, never the JWT, key, code or session id | confirmed
- D4 Consent flow: `POST /bank/connect` reads the ASPSP's `maximum_consent_validity` and asks for `valid_until` = now + that many seconds − 10 minutes. It makes a state with `secrets.token_urlsafe(32)` and stores only its SHA-256 hash and creation time; a new Connect replaces any pending one. It then calls POST `/auth` (`access.valid_until`, `aspsp`, `state`, `redirect_url`, `psu_type` "personal") and answers 303 to the returned url. `GET /bank/callback?code&state` deletes the pending state on every call. It accepts the state only when `hmac.compare_digest` matches the hash and the state is under 30 minutes old. It then calls POST `/sessions` with the code. It stores the session id, the account uid (the only account, or else the first with `cash_account_type` "CACC"), the IBAN's last 4 characters and the consent end from the session's `access.valid_until`, replacing any earlier connection, and answers 303 to /settings. A bad, missing, reused or expired state, a bank `error` parameter or an API error re-renders /settings with status 400 and the inline `#form-error` "The bank connection did not complete. Start again with Connect bank.", and stores nothing. No bank path is public: the sign-in gate covers them all (src/sonar/web/access.py:25,37) | confirmed
- D5 Storage: one additive migration, numbered with the next free number in src/sonar/migrations/ when it runs: 0012, or 0013 if the energy-monitor plan has taken 0012. Table `bank_connection` is a single row (id = 1) with `session_id`, `account_uid`, `iban_last4`, `consent_valid_until` (UTC ISO datetime), `connected_at`, `last_sync_at`, `last_sync_status` (`ok`/`error`/null), `last_sync_added` and `last_sync_error`. Table `bank_authorization` is a single row with `state_hash` and `created_at`. A reconnect replaces the session fields and keeps the last-sync fields | confirmed
- D6 Banner: shown on every non-bare page, only when the feature is on and a connection exists. It loads by htmx from `GET /bank/banner`, like the Uncategorized badge (src/sonar/web/templates/base.html:108), into a slot above `{% block content %}` (base.html:149); the fragment is empty when there is nothing to say. Each case below has a Reconnect button (a POST form to /bank/connect), and the failed case also has Sync now. When more than one case applies, the first listed wins: expired (today ≥ consent end date): "Bank access ended on <date>."; failed (last sync status error): "The bank sync on <date> failed: <error>."; expiring (today ≥ consent end − 14 days): "Bank access ends on <date>."; never connected: nothing | confirmed
- D7 Settings and API: with the feature on, /settings gets a "Bank connection" card (`#bank-card`). It shows the status (Not connected, Connected, Ends soon, Expired), "Deutsche Bank ···<last4>", the consent end, the last sync (time, ok or failed, rows added, error), a Connect bank or Reconnect bank button and Sync now. Sync now is `POST /bank/sync`: it runs the sync and answers 303 to /settings. For API parity (SPEC §13): `GET /api/bank` returns the same status as JSON, with no session id or account uid; `POST /api/bank/sync` runs the sync and returns that status, answering 409 when not connected and 502 when Enable Banking fails. Connect stays page-only because it is a browser redirect | confirmed
- D8 Sync: `sonar bank-sync [--db]`. Not configured: prints "Bank sync is not configured." and exits 0. Configured but not connected: prints "Bank is not connected." and exits 0. Otherwise it fetches the booked transactions from `date_from` to today and the balances, imports the rows through the import pipeline and re-applies rules and recurring detection as the upload does (src/sonar/web/pages/import_.py:57-62). It records the balance as of the sync date as source 'import', upserted so the day's latest sync wins. It records `last_sync_at`, the status and the rows added. On success it prints "Bank sync: N added, M duplicates, balance X on D." and exits 0. On any error it records status error with the short message, prints "Bank sync failed: <message>" and exits 1. Later syncs start at the last successful sync date − 7 days, and dedup drops the repeats. The first window follows D9. The service takes `today`, `now` and the client as parameters | confirmed
- D9 CSV/API overlap: the owner picks it at gate N05 after reading the N04 report, and the planner then replans N07 to that choice. N07's brief is written for A. A: the API takes over from a cutover date. At the first sync the cutover is the day after the latest booking date of the stored Deutsche Bank CSV rows, or 90 days back if there are none, and it is stored on the connection. API rows from the cutover on are deduplicated by their Enable Banking transaction id: the fingerprint becomes a hash of "enable-banking", the account and the id, with occurrence 1. From then on CSV uploads of the Girokonto import only rows booked before the cutover. B: API rows use the normal fingerprint, and an API row that matches a stored row on account, booking date, amount and normalized counterparty counts as a duplicate | confirmed
- D10 Details settled at N05 from the report, recorded without real values: the rule that gives API rows the same `account` string as the stored Girokonto CSV rows, the transaction id field, the fields for mandate reference and creditor id, and the balance type. Defaults the brief assumes: the id is `entry_reference`, else `transaction_id`; the balance is `CLBD`, else `ITBD`, else the first one listed | confirmed
- D11 Deploy: Terraform variables `enable_banking_app_id` (default "") and `enable_banking_private_key` (sensitive PEM text, default ""); both or neither must be set. When set, install.sh puts the key at `/etc/sonar/enable-banking.pem` (0640 root:sonar), and `sonar.env` gets both env vars. When unset, the key file is removed. Units `sonar-bank-sync.service` (oneshot, User=sonar, EnvironmentFile, `ExecStart=/opt/sonar/.venv/bin/sonar bank-sync`, RequiresMountsFor=/var/lib/sonar) and `sonar-bank-sync.timer` (`OnCalendar=*-*-* 06:30:00 Europe/Berlin`, `Persistent=true`), always installed and enabled. ci.yml passes the GitHub variable `ENABLE_BANKING_APP_ID` and the secret `ENABLE_BANKING_PRIVATE_KEY` as `TF_VAR_`s. deploy/README.md documents the setup | confirmed
- D12 Real data: the first-authorization file `data/enable-banking-session.json` (mode 0600) and the report `data/enable-banking-comparison.md` live only in the gitignored `data/`. Tracked files, tests, commit messages and the plan log never hold real values. Fixtures are hand-written, anonymized Enable Banking payloads, and tests generate a throwaway RSA key at runtime | confirmed
- D13 Pre-authorized mid-run: at N03, the orchestrator writes and runs a scratch helper (session scratchpad, never the repo) that makes the first authorization; at N04, the executor calls Enable Banking with the owner's key and reads `data/sonar.db` read-only; the visual gate's scratch launcher (D14). The plan never pushes or deploys: the owner deploys at N10 | confirmed
- D14 Visual gate setup: a scratch launcher (session scratchpad) runs `create_app` on a temp DB with bank settings, a throwaway key in `$TMPDIR` and a fake Enable Banking client (no network). The fake's Connect goes straight to /bank/callback with the right state. The launcher seeds the states not connected, connected, ending in 10 days, expired and failed sync. `create_app` therefore takes an injected bank client, as it does `google` (src/sonar/web/app.py:82-87) | confirmed
- D15 Tier M with 11 nodes, as requested, with every brief written now and N07 rewritten after N05. Planzilla §1 would move a graph of more than 10 nodes to L | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 1 | DONE | |
| N02 | SPEC and bank settings | exec | N01 | sonnet/opus | 1 | 1 | DONE | |
| N03 | owner Enable Banking setup and first authorization | gate | N12 | -/- | 0 | 0 | TODO | |
| N04 | API vs CSV comparison report | exec | N03 | opus/sonnet | 0 | 0 | TODO | |
| N05 | overlap strategy | gate | N04 | -/- | 0 | 0 | TODO | |
| N06 | connection store and consent rules | exec | N12 | sonnet/sonnet | 1 | 1 | DONE | |
| N07 | daily sync into the import pipeline | exec | N05,N14 | opus/opus | 0 | 0 | TODO | |
| N08 | systemd timer and Terraform install | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N09 | visual check | gate | N07 | -/- | 0 | 0 | TODO | |
| N10 | owner live check on prod | gate | N08,N09 | -/- | 0 | 0 | TODO | |
| N11 | plan acceptance | check | N10 | -/sonnet | 0 | 0 | TODO | |
| N12 | Enable Banking client | exec | N02 | sonnet/opus | 1 | 0 | DONE | |
| N13 | Connect flow and Settings card | exec | N06 | sonnet/opus | 1 | 0 | DONE | |
| N14 | bank banner | exec | N13 | sonnet/sonnet | 1 | 1 | DONE | |

## N01 preflight
Do: Confirm the starting point before any work: verify passes on the untouched tree; the JWT, crypto and HTTP
  libraries import; the Tailwind CLI builds; Terraform validates; Enable Banking's API host answers; `data/` is
  gitignored; and the repo is writable.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `uv run python -c "import authlib.jose, cryptography, httpx"` exits 0
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C4 [cmd] `ASDF_TERRAFORM_VERSION=1.16.5 terraform -chdir=deploy/terraform fmt -check main.tf variables.tf outputs.tf versions.tf && ASDF_TERRAFORM_VERSION=1.16.5 terraform -chdir=deploy/terraform validate`
  exits 0: the asdf shim gets CI's version (.github/workflows/ci.yml:59), and fmt checks only the tracked .tf files,
  never the gitignored `terraform.tfvars`
- C5 [cmd] `curl -sS -o /dev/null -w '%{http_code}' https://api.enablebanking.com/aspsps` prints an HTTP status
  (401 without a JWT is fine), which proves the host is reachable
- C6 [cmd] `git check-ignore -q data/enable-banking-comparison.md && git check-ignore -q data/enable-banking-session.json`
- C7 [cmd] `test -w .git/index && git status --porcelain >/dev/null` exits 0

## N02 SPEC and bank settings
Do: Amend SPEC for the bank sync and add its pure env settings; the HTTP client is N12.
  - SPEC.md:10: replace that bullet with "- Data comes in by file upload and, for the Deutsche Bank Girokonto, by
    a daily Enable Banking sync (§13 Bank sync)."
  - After SPEC.md:258, the last §13 bullet, append this bullet word for word: "- Bank sync (§0, §4, §8): with
    SONAR_ENABLE_BANKING_APP_ID and SONAR_ENABLE_BANKING_KEY_PATH set (both or neither, else `sonar` refuses to
    start; the key file must be readable and outside the served static files), Sonar reads the Deutsche Bank
    Girokonto from Enable Banking. Connect bank on the Settings Bank connection card sends the owner to the bank
    for the longest consent it allows (about 180 days) and back to /bank/callback, which accepts only the
    single-use state it issued in the last 30 minutes. `sonar bank-sync`, run daily at 06:30 Berlin time, by Sync
    now and by `POST /api/bank/sync`, imports the booked transactions from 7 days before the last successful sync,
    and the balance, through the import pipeline, then re-applies rules and recurring detection. A banner on every
    page says when the consent ends within 14 days, has ended, or the last sync failed, with Reconnect.
    `GET /api/bank` returns the status. With neither variable set, none of this exists."
  - `.env.example`: append both variables, empty, with comments: the app id; the key `.pem` path, outside the repo, mode 600.
Context: new package `src/sonar/banking/` with an empty `__init__.py`; tests in `tests/banking/` with an empty
  `__init__.py`, as tests/auth/ has. `banking/settings.py` is pure, modelled on src/sonar/auth/settings.py:11-54:
  - `BANK_ENV_VARS` = the two names above; `ASPSP_NAME = "Deutsche Bank"`; `ASPSP_COUNTRY = "DE"`.
  - frozen dataclass `BankSettings(app_id: str, key_path: Path, redirect_url: str)`.
  - `bank_settings(env: Mapping[str, str]) -> BankSettings | None`: both unset or empty → None; one → ValueError
    "Bank sync is only partly configured; missing: <name>". redirect_url = `SONAR_BASE_URL` without a trailing
    "/", else `http://127.0.0.1:<SONAR_PORT, else 8000>`, plus "/bank/callback".
  - `read_private_key(path: Path, served_dir: Path) -> bytes` returns the file's bytes. It raises ValueError naming
    the path, never the contents (`raise ... from None`), when `path.resolve()` lies inside `served_dir.resolve()`,
    when reading raises OSError, or when `cryptography.hazmat.primitives.serialization.load_pem_private_key(data,
    None)` rejects the bytes. N06 passes src/sonar/web/static; banking never imports sonar.web
    (tests/test_architecture.py). Nothing here prints, logs or reads `os.environ`.
Read: `src/sonar/auth/settings.py`, `tests/auth/test_settings.py`, `SPEC.md:1-12`, `SPEC.md:225-258`, `.env.example`
Write: `SPEC.md`, `.env.example`, `src/sonar/banking/__init__.py`, `src/sonar/banking/settings.py`, `tests/banking/__init__.py`, `tests/banking/test_settings.py`
Test first: `bank_settings({})` is None; it fails today because `sonar.banking` does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/banking/test_settings.py -k bank_settings` passes tests for: both unset or empty
  → None; one set → ValueError naming it; redirect_url from SONAR_BASE_URL ("/" dropped), SONAR_PORT, or 8000
- C2 [cmd] `uv run pytest -q tests/banking/test_settings.py -k private_key` passes tests for: a valid key (an RSA key
  made with `cryptography` at runtime in `tmp_path`) → its bytes; a key under served_dir, also when reached by a
  symlink from outside, a missing path, a directory and a non-PEM file → ValueError naming the path and holding none of the file's text
- C3 [review] SPEC.md:10 no longer says not to build a bank connection; the §13 Bank sync bullet reads as given;
  `.env.example` has both variables empty; settings.py never prints, logs, reads the clock or `os.environ`; no key
  file is committed
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N12 Enable Banking client
Do: Add `src/sonar/banking/client.py`, a thin HTTP shell that signs every Enable Banking request with the app
  key and returns raw payload dicts; the mapping is N07.
Context: `BASE_URL = "https://api.enablebanking.com"`; requests use absolute URLs on it. `default_http()` returns
  `httpx.Client(timeout=30.0, verify=True)`: TLS verification is explicit and never off.
  - `EnableBankingClient(app_id: str, private_key_pem: bytes, http: httpx.Client, now: Callable[[], datetime])`;
    `now` returns an aware UTC datetime; tests fix it and pass `httpx.Client(transport=httpx.MockTransport(...))`.
  - Every request sends `Authorization: Bearer <jwt>` from `authlib.jose.jwt.encode`. authlib is already a
    dependency and brings `cryptography`, so add no package and leave pyproject.toml alone; its import-time
    AuthlibDeprecationWarning is harmless. Header `{"alg": "RS256", "typ": "JWT", "kid": app_id}`; claims `iss`
    "enablebanking.com", `aud` "api.enablebanking.com", `iat` = int(now().timestamp()), `exp` = iat + 3600.
  - `aspsps(country: str) -> list[dict]`: GET `/aspsps` with query `country`; returns the answer's `aspsps`.
  - `start_authorization(valid_until: datetime, state: str, redirect_url: str) -> dict`: POST `/auth`, JSON
    `{"access": {"valid_until": valid_until.isoformat()}, "aspsp": {"name": ASPSP_NAME, "country": ASPSP_COUNTRY},
    "state": state, "redirect_url": redirect_url, "psu_type": "personal"}`, constants from banking/settings.py.
  - `create_session(code: str) -> dict`: POST `/sessions`, JSON `{"code": code}`.
  - `booked_transactions(account_uid: str, date_from: date, date_to: date) -> list[dict]`: GET
    `/accounts/{account_uid}/transactions` with ISO `date_from` and `date_to` and `transaction_status=BOOK`; while
    an answer has a non-empty `continuation_key`, repeat with it added; returns all pages' `transactions` joined.
  - `balances(account_uid: str) -> list[dict]`: GET `/accounts/{account_uid}/balances`; returns `balances`.
  - `BankApiError(Exception)` has `status: int | None` and `message`. A non-2xx answer gives "Enable Banking
    answered <status>", plus " (<error>)" when the JSON body's `error` is a string that `re.fullmatch`es `[A-Z_]{1,40}`. An
    `httpx.HTTPError` gives status None and "Enable Banking could not be reached", raised `from None`. The text
    never holds the JWT, key, code, session id, URL or body, and is at most 200 characters.
  Nothing prints, logs or calls `datetime.now`/`date.today`; tests use a runtime RSA key and made-up payloads only.
Read: `src/sonar/banking/settings.py`, `tests/banking/test_settings.py`
Write: `src/sonar/banking/client.py`, `tests/banking/test_client.py`
Test first: `booked_transactions` sends a Bearer JWT that `authlib.jose.jwt.decode` verifies with the test public
  key; it fails today because `sonar.banking.client` does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/banking/test_client.py -k jwt` passes tests for the header (alg, typ, kid) and
  the claims (iss, aud, iat from `now`, exp = iat + 3600)
- C2 [cmd] `uv run pytest -q tests/banking/test_client.py -k "aspsps or authorization or session or transactions or balances"`
  passes tests for the method, path, query and JSON body of all five calls, and two pages joined by `continuation_key`
- C3 [cmd] `uv run pytest -q tests/banking/test_client.py -k "error or timeout"` passes tests for: a 401 with
  `{"error": "EXPIRED_SESSION"}` → status 401 and that code in the text; an `error` off the pattern is left out;
  `httpx.ConnectError` from the transport → status None; no text holds the JWT, the code or a session id echoed in
  the body; `default_http().timeout` is 30 s
- C4 [review] TLS verification is on with no switch to turn it off; no print, log or clock call; the error text rules hold
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 owner Enable Banking setup and first authorization
Do: gate for the owner, with the helper pre-authorized (D13).
  1. In the Enable Banking Control Panel the owner creates a production application in restricted mode, keeps
     its private key `.pem` outside the repo (chmod 600), and registers the redirect URLs: prod
     `https://<sonar host>/bank/callback`, plus `http://127.0.0.1:8000/bank/callback` if the panel accepts it.
  2. The owner links the Deutsche Bank Girokonto to the app.
  3. The owner sets `SONAR_ENABLE_BANKING_APP_ID` and `SONAR_ENABLE_BANKING_KEY_PATH` in the local `.env`.
  4. The owner makes sure `data/sonar.db` holds Girokonto CSV imports up to recent days: a copy of the prod DB,
     or the newest export imported locally.
  5. The orchestrator writes a scratch helper in the session scratchpad on `sonar.banking.client`. It lists the
     DE ASPSPs whose name contains "Deutsche Bank" and prints the names and `maximum_consent_validity`. It calls
     POST /auth with a fresh state and a registered redirect URL, and prints the authorization URL.
  6. The owner authorizes at the bank and pastes back the full URL the browser lands on. On prod, while signed
     in, that page is a 404 whose address bar still holds `code` and `state`.
  7. The helper checks the state, calls POST /sessions and writes only `session_id` and the account uids to
     `data/enable-banking-session.json`, mode 0600. It prints no secret.
Done when:
- C1 [human] the owner confirms the restricted-mode app exists, the Girokonto is linked, and the key lives outside
  the repo with mode 600
- C2 [cmd] `test "$(stat -f %Lp data/enable-banking-session.json)" = 600 && git check-ignore -q data/enable-banking-session.json`
- C3 [human] the exact ASPSP name the helper listed for the Girokonto is recorded in the log; if it differs from
  "Deutsche Bank", D2 gets a mid-run revision

## N04 API vs CSV comparison report
Do: Write a local report, for the owner only, that compares what Enable Banking returns for the Girokonto with the
  CSV rows already in the DB over the same dates, so the owner can choose the overlap strategy at N05. Use a
  scratch script in your session scratchpad, never in the repo. It reads the session from
  `data/enable-banking-session.json` and the app id and key path from `.env`, and fetches booked transactions for
  the last 90 days twice plus the balances. It opens `data/sonar.db` read-only (sqlite URI `mode=ro`), never
  through `sonar.db.connect`, which migrates.
Context: D9 options A and B; D10 lists what the owner settles. The CSV importer layout is in
  src/sonar/importing/importers/deutsche_bank_giro.py:1-30 and the fingerprint in src/sonar/importing/dedup.py:24-35.
  The report covers:
  1. counts per side in the overlapping dates;
  2. matches under the current fingerprint with the most faithful mapping, under date+amount+normalized
     counterparty, and under date+amount, with reasons for the unmatched rows;
  3. for every `ParsedTransaction` field, the API field it comes from and how often it equals the CSV value;
  4. whether `entry_reference` and `transaction_id` are present, unique and the same in both fetches;
  5. the balance types and dates returned, against the latest CSV balance;
  6. how the CSV `account` string relates to the API's account identifiers;
  7. the risks of A and B, with a recommendation.
  D12: the report may hold real rows because `data/` is gitignored, but at most 5 example pairs. Your reply and
  any log line hold only counts and field names.
Read: `src/sonar/importing/importers/deutsche_bank_giro.py`, `src/sonar/importing/dedup.py`, `src/sonar/banking/client.py`, `src/sonar/migrations/0001_import.sql`
Write: `data/enable-banking-comparison.md`
Test first: -
Done when:
- C1 [cmd] `test -s data/enable-banking-comparison.md && git check-ignore -q data/enable-banking-comparison.md`
- C2 [review] the report has the 7 sections above with numbers, and holds no JWT, private key, session id or code
- C3 [cmd] `test -z "$(git status --porcelain -- src tests SPEC.md)"` shows no tracked change
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 overlap strategy
Do: gate for the owner. The owner reads `data/enable-banking-comparison.md` and picks the CSV/API overlap strategy:
  - A: the API takes over from a cutover date; API rows are deduplicated by their Enable Banking transaction id,
    and CSV rows import only before the cutover.
  - B: API rows match CSV rows on date + amount + counterparty.
  The owner also confirms D10: the account label rule, the id field, the mandate and creditor id fields, and the
  balance type. The orchestrator adds the answers as Decisions with field names only (no real values) and asks
  the planner for `Replan: N07`.
Done when:
- C1 [human] the owner names A or B, and each D10 item, and the Decisions record them without real data
- C2 [human] N07's brief has been rewritten to follow the choice before N07 starts

## N06 connection store and consent rules
Do: Add the bank connection tables, `banking/store.py` and the pure `banking/consent.py` (SPEC §13 Bank sync).
  consent.py, no clock and no I/O except `new_state`:
  - `BankConnection` (frozen dataclass: the `bank_connection` columns below, datetimes tz-aware UTC) and
    `NewConnection` (session_id, account_uid, iban_last4, consent_valid_until, connected_at);
  - `consent_seconds(aspsps, name)`: `maximum_consent_validity` of the ASPSP with that `name`, else ValueError;
  - `requested_valid_until(now, seconds)` = now + seconds − 10 minutes;
  - `new_state()` = `secrets.token_urlsafe(32)`; `state_hash(state)` = SHA-256 hex;
  - `state_matches(state, stored_hash, created_at, now)`: `hmac.compare_digest` on the hashes and
    now − created_at < 30 minutes;
  - `parse_session(session, now) -> NewConnection`: `session_id`; the only entry of `accounts`, else the first
    with `cash_account_type` "CACC"; its `uid` and the last 4 characters of `account_id.iban`; consent end from
    `access.valid_until` as UTC. A missing field or no usable account raises ValueError;
  - `banner(connection, today) -> Banner | None` (`kind`, `on`: date, `error`), first match wins: "expired" when
    today ≥ the consent end date; "failed" when `last_sync_status` is "error" (`on` = last sync date, `error`
    its message); "expiring" when today ≥ consent end date − 14 days; None when never connected or none apply;
  - `card_status(connection, today)`: "Not connected", "Expired", "Ends soon" or "Connected", same thresholds.
  store.py: `load_connection`, `save_connection(conn, new)` (upsert id 1: replaces the session fields, keeps the
  last-sync fields), `save_pending_state(conn, state_hash, created_at)` (replaces any pending one) and
  `take_pending_state(conn)` (returns hash and created_at, or None, and always deletes the row).
Context: Migration = the next free number in src/sonar/migrations/ (0012 today, after 0011_debts_purpose_match.sql),
  named `NNNN_bank_connection.sql`, CREATE TABLE only. `bank_connection`: `id` INTEGER PRIMARY KEY CHECK (id = 1),
  `session_id`, `account_uid`, `iban_last4`, `consent_valid_until`, `connected_at` (TEXT NOT NULL, datetimes as UTC
  ISO), `last_sync_at` TEXT, `last_sync_status` TEXT CHECK IN ('ok','error'), `last_sync_added` INTEGER,
  `last_sync_error` TEXT, all three nullable. `bank_authorization`: `id` CHECK (id = 1), `state_hash`, `created_at`.
  Only the hash of a state is ever stored. Store style: src/sonar/cashflow/store.py:33-62. sqlite3 is allowed only
  in store modules (tests/test_architecture.py:46-55). Tests use hand-written anonymized payloads, no real values.
Read: `src/sonar/cashflow/store.py`, `src/sonar/db.py`, `src/sonar/banking/settings.py`, `src/sonar/migrations/0005_settings.sql`, `tests/cashflow/test_store.py`
Write: `src/sonar/migrations/*_bank_connection.sql`, `src/sonar/banking/consent.py`, `src/sonar/banking/store.py`, `tests/banking/test_consent.py`, `tests/banking/test_store.py`
Test first: `requested_valid_until(now, 15552000)` is now + 180 days − 10 minutes; fails today: no consent.py.
Done when:
- C1 [cmd] `uv run pytest -q tests/banking/test_consent.py` passes tests for: valid_until; `consent_seconds` found
  and missing; a matching, wrong and 30-minute-old state; `parse_session` with one account, two accounts (CACC
  wins) and none; banner at 15 days before the end (None), 14 days (expiring), on the end date (expired), after a
  failed sync (failed), expired beating failed, never connected (None); the four card statuses
- C2 [cmd] `uv run pytest -q tests/banking/test_store.py` passes tests for: no connection → None; save then load
  round-trips; a second save replaces the session fields and keeps the last-sync fields; take_pending_state
  returns the saved hash once, then None; a new pending state replaces the old one
- C3 [review] the migration only creates the two tables; consent.py is pure but for `new_state`; no plain state stored
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N13 Connect flow and Settings card
Do: Wire the bank connection into the app (SPEC §13 Bank sync); the banner is N14, Sync now is N07.
  - `create_app` gains `now` (default UTC clock), `bank: BankSettings | None` and `bank_client` (an object with
    `aspsps`, `start_authorization`, `create_session`, as src/sonar/banking/client.py:48-62), and sets
    `app.state.bank_enabled`. With `bank` None nothing below exists: bank routes 404 and no card.
  - `serve()`: `bank_settings(os.environ)`, `read_private_key(key_path, STATIC_DIR)`; a ValueError prints and exits 1
    before uvicorn, like src/sonar/__main__.py:71-76; else passes `bank` and `EnableBankingClient(…, default_http(), now)`.
  - `web/pages/bank.py`, using only banking.consent and banking.store:
    - `POST /bank/connect`: `consent_seconds(aspsps(ASPSP_COUNTRY), ASPSP_NAME)`, `new_state()`, then
      `save_pending_state(state_hash(state), now)` and `start_authorization(requested_valid_until(now, seconds),
      state, bank.redirect_url)`; 303 to the answer's `url`;
    - `GET /bank/callback?code&state&error`: `take_pending_state` first, on every call. Accept only with no `error`,
      both params and `state_matches`; then `save_connection(parse_session(create_session(code), now))`; 303 /settings;
    - any failure in either route (bad, missing, reused or expired state, `error`, BankApiError, ValueError)
      re-renders /settings with 400 and `#form-error` "The bank connection did not complete. Start again with
      Connect bank." and stores no connection.
  - settings.py: lift `_render_settings_page` (src/sonar/web/pages/settings.py:22-37) to a module-level function
    that bank.py calls too; with the feature on it adds the connection and `card_status`.
  - settings.html: a "Bank connection" card `#bank-card` with `data-bank-status` (the status in lower-kebab case),
    the status, "Deutsche Bank ···<last4>", the consent end (`date` filter), the last sync (time, ok or failed, rows
    added, error), the bank `#form-error` and a POST form `#bank-connect` "Connect bank" (not connected) or
    "Reconnect bank". Rebuild sonar.css (AGENTS.md Setup).
Context: The sign-in gate already covers /bank/* (src/sonar/web/access.py:25,37). `tests/web/fake_bank.py`, like
  fake_google.py: `aspsps` lists Deutsche Bank, DE, `maximum_consent_validity` 15552000; `start_authorization`
  records the state, returns a fake url; `create_session` returns an anonymized session or raises a set BankApiError.
Read: `src/sonar/web/app.py`, `src/sonar/web/pages/settings.py`, `src/sonar/web/templates/settings.html`, `src/sonar/__main__.py`, `src/sonar/banking/consent.py`, `src/sonar/banking/store.py`, `tests/web/fake_google.py`, `tests/web/test_auth_pages.py`, `tests/html.py`, `tests/test_main.py:60-133`
Write: `src/sonar/web/pages/bank.py`, `src/sonar/web/pages/settings.py`, `src/sonar/web/app.py`, `src/sonar/__main__.py`, `src/sonar/web/templates/settings.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_bank_pages.py`, `tests/web/fake_bank.py`, `tests/test_main.py`
Test first: with the fake, `POST /bank/connect` answers 303 to the fake url; `GET /bank/callback` with that state
  and a code then shows `data-bank-status="connected"` in `#bank-card`. It fails today: there is no route.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_bank_pages.py -k "connect or callback"` passes: the connect redirect; a
  valid callback stores and shows ···last4; a second one replaces it; a wrong, reused or 31-minute-old state, an
  `error` param and a BankApiError each give 400 with `#form-error` and no connection stored
- C2 [cmd] `uv run pytest -q tests/web/test_bank_pages.py tests/test_main.py -k "off or partial or key"` passes:
  off → both routes 404, no `#bank-card`; a partial env and a key path at the served sonar.css exit 1, no uvicorn
- C3 [cmd] `uv run pytest -q tests/web/test_bank_pages.py -k sign_in` passes: with sign-in on, a signed-out GET
  /bank/callback redirects to /auth/login and stores nothing; a signed-in GET /bank/connect answers 405
- C4 [review] no template, response or print holds a session id, code, state, JWT or key; bank.py has no sqlite3;
  routes live only in pages/bank.py; sonar.css is rebuilt
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N14 bank banner
Do: Add the bank banner on every page (SPEC §13 Bank sync); its Sync now button comes in N07.
  - `GET /bank/banner` in src/sonar/web/pages/bank.py renders `bank_banner.html` for
    `banner(load_connection(conn), today)` (src/sonar/banking/consent.py); the fragment is empty when it is None.
  - base.html: on non-bare pages, only when `request.app.state.bank_enabled`, a `#bank-banner-slot` loads
    `/bank/banner` by htmx like the Uncategorized badge (base.html:108: `hx-trigger="load"`, `hx-swap="outerHTML"`),
    placed inside `<main>` just above `{% block content %}` (base.html:149).
  - bank_banner.html: `#bank-banner` with `data-banner` = the banner kind, built from the components/ macros, and
    the text, dates with the `date` filter:
    - expired: "Bank access ended on <date>.";
    - failed: "The bank sync on <date> failed: <error>.";
    - expiring: "Bank access ends on <date>.".
    Each case has a Reconnect button: a POST form to /bank/connect. Rebuild sonar.css (AGENTS.md Setup).
  - tests/web/test_templates_hygiene.py:41: add `bank_banner.html` to the `fragments` set (it is an htmx
    fragment, so it does not extend base.html).
Context: Which case applies, and its date and error, is already decided by `banner`; the template only renders it.
  With `bank` None (the feature off) the route is 404 and no page holds the slot. Tests build the app as
  tests/web/test_bank_pages.py does, with tests/web/fake_bank.py, and seed the connection through
  `banking.store.save_connection`; a failed sync is seeded with a direct UPDATE in the test.
Read: `src/sonar/web/pages/bank.py`, `src/sonar/banking/consent.py`, `src/sonar/banking/store.py`, `src/sonar/web/templates/base.html:95-150`, `src/sonar/web/templates/components/button.html`, `tests/web/test_bank_pages.py`, `tests/html.py`, `tests/web/test_templates_hygiene.py:35-50`
Write: `src/sonar/web/pages/bank.py`, `src/sonar/web/templates/base.html`, `src/sonar/web/templates/bank_banner.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_bank_banner.py`, `tests/web/test_templates_hygiene.py`
Test first: with a connection ending in 10 days, `GET /bank/banner` holds `#bank-banner` with
  `data-banner="expiring"`. It fails today because the route does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_bank_banner.py` passes: no connection → an empty fragment; the
  expired, failed and expiring fragments with their `data-banner`, text and a POST form to /bank/connect
- C2 [cmd] `uv run pytest -q tests/web/test_bank_banner.py -k "slot or off"` passes: `#bank-banner-slot` with
  `hx-get="/bank/banner"` on / and /settings when on; off → /bank/banner 404 and no slot on / or /settings
- C3 [review] the template has no inline style, holds no session id or account uid, sonar.css is rebuilt, and
  the hygiene test's only change is `bank_banner.html` added to `fragments`
- C4 [cmd] `uv run pytest -q tests/web/test_templates_hygiene.py` passes
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 daily sync into the import pipeline
Do: Map Enable Banking booked transactions and the balance to the import dataclasses (pure, `banking/mapping.py`)
  and import them through the existing pipeline with overlap strategy A (D9, as confirmed at N05). Add
  `banking/service.sync`; the `sonar bank-sync` command; `POST /bank/sync` and Sync now in `#bank-card` and in the
  failed banner; `GET /api/bank` and `POST /api/bank/sync`. Append the overlap rule to SPEC's §13 Bank sync bullet.
  Rebuild `sonar.css`.
Context: D10, as confirmed at N05, gives the account label, id field, mandate/creditor fields and balance type.
  Mapping:
  - amount = Decimal(`transaction_amount.amount`) in exact cents, negative for `DBIT`;
  - counterparty = `creditor.name` for DBIT, `debtor.name` for CRDT; iban from the other side's account;
  - purpose = the `remittance_information` lines joined by a space;
  - value_date falls back to booking_date;
  - raw_row = `json.dumps(tx, sort_keys=True, ensure_ascii=False)`.
  Pipeline: extract the shared insert path from src/sonar/importing/store.py:31-70,118-125 so file and API
  imports share it. API rows use source "Deutsche Bank Girokonto API".
  A: at the first sync the cutover is stored on the connection (a migration adds the column), and later syncs
  never fetch before it. Each API row's fingerprint is sha256 of `["enable-banking", account, id]`, occurrence 1.
  `import_file` skips `deutsche_bank_giro.NAME` rows (src/sonar/importing/importers/deutsche_bank_giro.py:37)
  booked on or after the cutover and counts them as duplicates.
  D8 covers the windows, messages, exit codes and balance upsert; D7 the routes and the 409/502 answers.
Read: `src/sonar/importing/store.py`, `src/sonar/importing/dedup.py`, `src/sonar/transactions.py`, `src/sonar/banking/client.py`, `src/sonar/banking/store.py`, `src/sonar/web/pages/bank.py`, `src/sonar/web/pages/import_.py`, `src/sonar/web/api/__init__.py`, `src/sonar/web/api/settings.py`, `src/sonar/__main__.py`, `tests/importing/test_store.py`
Write: `SPEC.md`, `src/sonar/migrations/*_bank_cutover.sql`, `src/sonar/banking/mapping.py`, `src/sonar/banking/service.py`, `src/sonar/banking/store.py`, `src/sonar/importing/store.py`, `src/sonar/__main__.py`, `src/sonar/web/pages/bank.py`, `src/sonar/web/api/bank.py`, `src/sonar/web/api/__init__.py`, `src/sonar/web/templates/settings.html`, `src/sonar/web/templates/bank_banner.html`, `src/sonar/web/static/sonar.css`, `tests/banking/**`, `tests/importing/test_store.py`, `tests/web/test_bank_pages.py`, `tests/web/test_api_bank.py`, `tests/test_cli_bank.py`
Test first: `mapping.transactions` turns an anonymized DBIT payload of "12.34" into −1234 cents with the
  creditor as counterparty. It fails today because the module does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/banking/test_mapping.py` passes the sign, exact cents, counterparty side,
  purpose join, value_date fallback, id and balance-type tests
- C2 [cmd] `uv run pytest -q tests/banking/test_service.py` passes:
  - the first sync sets the cutover and fetches from it; a later sync starts 7 days before the last success;
  - a repeated sync adds 0 rows; a CSV row on or after the cutover is skipped;
  - the balance is upserted as of today; an API error records the status error and keeps the earlier rows
- C3 [cmd] `uv run pytest -q tests/test_cli_bank.py tests/web/test_api_bank.py tests/web/test_bank_pages.py -k "sync or api"`
  passes the D8 output lines and exit codes, Sync now → 303 /settings, and /api/bank (no session id) with 409 and 502
- C4 [review] mapping and service never read the clock; sqlite appears only in store/service; nothing prints or
  stores a JWT, key or session id; SPEC's Bank sync bullet states the overlap rule; sonar.css is rebuilt
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 systemd timer and Terraform install
Do: Install a daily `sonar bank-sync` timer with the existing Terraform install, ship the Enable Banking app id and
  key to the VM, pass them from CI, and document the setup and the reconnect in deploy/README.md. The app stays
  deployable with both values unset.
Context: D11 for the variables, files, modes, units and the CI names. Follow the existing pattern:
  - render the files in `local.rendered`, which feeds the install triggers (deploy/terraform/main.tf:52-63,135-145);
  - upload them with file provisioners (main.tf:154-177);
  - install them in `install_config` (deploy/terraform/files/install.sh:87-100), then
    `systemctl enable --now sonar-bank-sync.timer`;
  - the env lines are conditional in deploy/terraform/templates/sonar.env.tftpl;
  - CI env goes in .github/workflows/ci.yml at the terraform apply step;
  - README: the GitHub table (deploy/README.md:226-240), a "Bank sync" section (create the restricted app,
    register `https://<host>/bank/callback`, set the var and secret, connect, reconnect before the consent ends),
    and Operations with `journalctl -u sonar-bank-sync` and `systemctl list-timers sonar-bank-sync.timer`.
  Never touch the gitignored `terraform.tfvars`.
Read: `deploy/terraform/main.tf`, `deploy/terraform/variables.tf`, `deploy/terraform/files/install.sh`, `deploy/terraform/templates/sonar.service.tftpl`, `deploy/terraform/templates/sonar.env.tftpl`, `deploy/terraform/terraform.tfvars.example`, `deploy/README.md`, `.github/workflows/ci.yml`
Write: `deploy/terraform/main.tf`, `deploy/terraform/variables.tf`, `deploy/terraform/terraform.tfvars.example`, `deploy/terraform/files/install.sh`, `deploy/terraform/templates/**`, `deploy/README.md`, `.github/workflows/ci.yml`
Test first: -
Done when:
- C1 [cmd] `ASDF_TERRAFORM_VERSION=1.16.5 terraform -chdir=deploy/terraform fmt -check main.tf variables.tf outputs.tf versions.tf && ASDF_TERRAFORM_VERSION=1.16.5 terraform -chdir=deploy/terraform validate`
  exits 0 (CI's version; tracked .tf files only)
- C2 [cmd] `bash -n deploy/terraform/files/install.sh && grep -q "OnCalendar=\*-\*-\* 06:30:00 Europe/Berlin" deploy/terraform/templates/sonar-bank-sync.timer.tftpl && grep -q "Persistent=true" deploy/terraform/templates/sonar-bank-sync.timer.tftpl`
- C3 [review] the key variable is sensitive and its validation needs both values or neither; the key lands 0640
  root:sonar and is removed when unset; the service unit is oneshot as User=sonar with RequiresMountsFor; the
  timer is enabled; ci.yml passes the two values without echoing them; the README covers setup, reconnect and
  logs
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 visual check
Do: gate, pre-authorized (D13, D14). Start the scratch launcher from the session scratchpad on a temp DB with
  bank settings, a throwaway key in `$TMPDIR` and the fake client. Then import the newest file in samples/, set
  the salary day and balance (config `visual_recipe`), and walk through:
  1. Connect bank from Settings;
  2. a successful Sync now;
  3. the seeded states: consent ending in 10 days, expired, and failed sync.
  Check /settings and the dashboard with the banner at desktop and 375px, light and dark (read_page first; scaled
  screenshots only where layout matters).
Done when:
- C1 [visual] `#bank-card` shows the status, "Deutsche Bank ···<last4>", the consent end, the last sync and the
  Connect or Reconnect and Sync now buttons, legible, with no overflow at 375px
- C2 [visual] the banner shows the right text for ending, ended and failed, with Reconnect (plus Sync now when
  failed), above the page content on every non-bare page, in all four views
- C3 [visual] when not connected the dashboard has no banner, and Connect lands back on /settings showing Connected

## N10 owner live check on prod
Do: gate for the owner (D11, D13).
  1. The owner adds the GitHub variable `ENABLE_BANKING_APP_ID` and the secret `ENABLE_BANKING_PRIVATE_KEY` to the
     `production` environment.
  2. The owner checks that `https://<host>/bank/callback` is a registered redirect URL.
  3. The owner deploys the committed tree themselves (push to main, or a local apply). The plan never pushes.
  4. On prod Settings: Connect bank, authorize at Deutsche Bank, Sync now.
  5. On the server: `systemctl start sonar-bank-sync.service`, `journalctl -u sonar-bank-sync -n 20` and
     `systemctl list-timers sonar-bank-sync.timer`.
Done when:
- C1 [human] after Connect, Settings shows Connected with a consent end about 180 days ahead
- C2 [human] the sync adds the transactions booked since the last CSV import, with no duplicates of CSV rows, and
  the dashboard shows the balance as of today
- C3 [human] `systemctl list-timers` lists `sonar-bank-sync.timer` with its next run at 06:30 Berlin time, and the
  journal shows the one-line "Bank sync:" summary with no secret in it

## N11 plan acceptance
Do: Check the whole plan against the SPEC, the security rules and the Definition of done.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [smoke] with no Enable Banking env, `uv run sonar` on a temp DB starts; /settings has no `#bank-card`;
  /bank/connect answers 404; `uv run sonar bank-sync --db <tmp>` prints "Bank sync is not configured." and exits 0
- C4 [review] SPEC §11 still holds, SPEC §12 UI acceptance holds for the card and the banner, and the §13 Bank
  sync bullet matches the built behavior
- C5 [review] security:
  - the state is hashed, single use and expires;
  - no bank path is public;
  - the key path is refused under static/;
  - no print, log, template or API answer holds a JWT, key, code or session id;
  - TLS verification is on;
  - errors are generic
- C6 [cmd] `test -z "$(git ls-files data samples)"` and no test fixture holds a real IBAN or name (D12)

## Log

### N01 try 1 · 2026-10-14
check: FAIL C4
- C4 exit 126: terraform 1.16.5

### N01 replan 1 · 2026-10-14
plan: REPLANNED
- cause: the asdf terraform shim has no version set in this repo (exit 126), and a plain fmt -check also fails on the gitignored, unformatted terraform.tfvars
- C4 now pins ASDF_TERRAFORM_VERSION=1.16.5 (CI's version) and fmt-checks only the tracked .tf files; checked by hand: fmt and validate exit 0
- N08 C1 gets the same command so it does not fail the same way

### N01 try 1 · 2026-10-14
check: PASS 7/7

### N02 try 1 · 2026-10-14
exec: BLOCKED · brief cites D2-D8 (env var names, JWT iss/aud, client paths, Bank sync bullet content) without stating them; cannot guess

### N02 replan 1 · 2026-10-14
plan: REPLANNED +N12
- cause: the brief cited D2-D8 without stating them and could not fit them in 40 lines with the client
- N02 is now SPEC, .env.example and banking/settings.py, with the SPEC.md:10 text, the §13 Bank sync bullet word for word, env names, redirect rule and read_private_key checks stated
- new N12 (deps N02) holds client.py: base URL, JWT header and claims, the five calls with paths, queries and bodies, BankApiError text rules; JWT via authlib.jose (cryptography comes with authlib), no PyJWT, no pyproject change
- N03 and N06 now depend on N12

### N02 try 1 · 2026-10-14
exec: DONE · 1362 passed
- SPEC §0 bullet and §13 Bank sync bullet, .env.example vars
- banking/settings.py: bank_settings, read_private_key (symlink-safe, no key text in errors)
- cryptography is used via authlib's transitive dependency; pyproject not in Write
check: PASS 3/3
verify: PASS

### N12 try 1 · 2026-10-14
exec: DONE · 1382 passed
- Added banking/client.py: JWT-signed Enable Banking client with five calls and BankApiError
- Non-JSON or non-matching error bodies give status-only text; 2xx body returned as response.json()

### N08 try 1 · 2026-10-14
exec: DONE · 1382 passed
- Terraform vars enable_banking_app_id/private_key (both-or-neither), bank-sync service+timer templates, install.sh key 0640 root:sonar and timer enable, ci.yml TF_VARs, README Bank sync
- Key uploaded always (empty file when unset); install.sh removes the key if empty

### N12 try 1 · 2026-10-14
check: PASS 4/4

### N08 try 1 · 2026-10-14
check: PASS 3/3
verify: PASS

### N12 try 1 · 2026-10-14
verify: PASS

### N06 try 1 · 2026-10-14
exec: BLOCKED · brief cites D2/D4/D5/D6/D7/D14 (tables, banner texts, card fields, flow) but does not include them; executor may not open the plan

### N06 replan 1 · 2026-10-14
plan: REPLANNED +N13,N14
- cause: the brief cited D2 D4-D7 D14 without stating them, and the store, flow, card and banner with their decisions could not fit one 40-line brief
- N06 is now the migration, banking/store.py and pure banking/consent.py, with table columns, function names, thresholds and banner precedence stated
- new N13 (deps N06): create_app/serve wiring, POST /bank/connect, GET /bank/callback steps and error text, #bank-card fields, fake_bank
- new N14 (deps N13): GET /bank/banner, base.html slot and banner texts
- N07 now depends on N05,N14; graph is 14 nodes, still tier M per D15

### N06 try 1 · 2026-10-14
exec: DONE · 1407 passed
- Added 0012_bank_connection.sql, banking/consent.py (pure rules) and banking/store.py
- Banner 'failed' uses today as date if last_sync_at is missing; naive consent end raises ValueError
check: PASS 3/3
verify: PASS

### N13 try 1 · 2026-10-14
exec: DONE · 1429 passed
- bank routes in pages/bank.py, render_settings_page lifted, bank card in settings.html, serve() wires bank settings and client
- sonar.css rebuilt, no class change; test_main create_app asserts now pass bank=None, bank_client=None
check: PASS 4/4
verify: PASS

### N14 try 1 · 2026-10-14
exec: BLOCKED · tests/web/test_templates_hygiene.py (outside Write) lists fragment templates; bank_banner.html must be added to its fragments set or test_templates_extend_base fails C4
- bank banner route, slot, template, tests and sonar.css done; test_bank_banner.py 10 passed; only that hygiene test fails

### N14 replan 1 · 2026-10-14
plan: REPLANNED
- cause: test_templates_extend_base fails because bank_banner.html is an htmx fragment not in the hygiene test's fragments set (tests/web/test_templates_hygiene.py:41), a file outside Write
- brief adds tests/web/test_templates_hygiene.py to Read/Write and a Do step to add bank_banner.html to fragments; new C4 runs the hygiene test, C3 reviews that change is the only exemption, verify moves to C5

### N14 try 1 · 2026-10-14
exec: DONE · 1439 passed
- GET /bank/banner, bank_banner.html and #bank-banner-slot in base.html; sonar.css rebuilt
- hygiene fragments set gains bank_banner.html
check: PASS 4/4
verify: PASS
