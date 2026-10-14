-- Enable Banking connection and the pending authorization (SPEC.md §13 Bank sync).
--
-- Both tables hold at most one row: Sonar reads a single bank account. Datetimes are UTC ISO
-- strings. Only the SHA-256 hash of the authorization state is stored, never the state itself.
CREATE TABLE bank_connection (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    session_id TEXT NOT NULL,
    account_uid TEXT NOT NULL,
    iban_last4 TEXT NOT NULL,
    consent_valid_until TEXT NOT NULL,
    connected_at TEXT NOT NULL,
    last_sync_at TEXT,
    last_sync_status TEXT CHECK (last_sync_status IN ('ok', 'error')),
    last_sync_added INTEGER,
    last_sync_error TEXT
);

CREATE TABLE bank_authorization (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    state_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
