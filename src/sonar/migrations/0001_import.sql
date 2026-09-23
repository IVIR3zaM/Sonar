-- Imported bank transactions and account balances (SPEC.md §4).
--
-- Idempotency: a re-imported row has the same fingerprint (a hash of the
-- normalized account, booking date, amount, counterparty and purpose text).
-- Genuinely identical rows within one file are numbered 1, 2, ... via
-- `occurrence`, so re-importing the same file matches the same
-- (fingerprint, occurrence) pairs and adds 0 rows, while two same-day
-- identical purchases are both kept.
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    account TEXT NOT NULL,
    booking_date TEXT NOT NULL,
    value_date TEXT,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    counterparty TEXT,
    purpose TEXT,
    iban TEXT,
    mandate_ref TEXT,
    creditor_id TEXT,
    raw_row TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    occurrence INTEGER NOT NULL,
    UNIQUE (fingerprint, occurrence)
);

-- Account balances, either read from an export or entered manually in
-- Settings. The entry with the latest `as_of` date wins (SPEC.md §4).
CREATE TABLE balances (
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL,
    as_of TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('import', 'manual')),
    UNIQUE (account, as_of, source)
);
