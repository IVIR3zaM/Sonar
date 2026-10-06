-- Debt purpose match (SPEC.md §13 Debt purpose match).
--
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt with
-- match_field also accepting 'purpose'. Every row keeps its id and values:
-- debts hold hand-entered data that must survive upgrades.
CREATE TABLE debts_new (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('installment', 'loan')),
    name TEXT NOT NULL CHECK (name <> ''),
    rate_cents INTEGER NOT NULL CHECK (rate_cents > 0),
    match_field TEXT NOT NULL CHECK (match_field IN ('counterparty', 'mandate', 'purpose')),
    match_value TEXT NOT NULL CHECK (match_value <> ''),
    total_cents INTEGER CHECK (total_cents > 0),
    interval_months INTEGER CHECK (interval_months >= 1),
    first_payment_date TEXT,
    payments_count INTEGER CHECK (payments_count >= 1),
    balance_cents INTEGER CHECK (balance_cents > 0),
    balance_as_of TEXT,
    interest_bp INTEGER CHECK (interest_bp > 0),
    CHECK (
        (kind = 'installment' AND
         total_cents IS NOT NULL AND
         interval_months IS NOT NULL AND
         first_payment_date IS NOT NULL AND
         payments_count IS NOT NULL AND
         balance_cents IS NULL AND
         balance_as_of IS NULL AND
         interest_bp IS NULL) OR
        (kind = 'loan' AND
         balance_cents IS NOT NULL AND
         balance_as_of IS NOT NULL AND
         total_cents IS NULL AND
         interval_months IS NULL AND
         first_payment_date IS NULL AND
         payments_count IS NULL)
    )
);

INSERT INTO debts_new (
    id, kind, name, rate_cents, match_field, match_value,
    total_cents, interval_months, first_payment_date, payments_count,
    balance_cents, balance_as_of, interest_bp
)
SELECT
    id, kind, name, rate_cents, match_field, match_value,
    total_cents, interval_months, first_payment_date, payments_count,
    balance_cents, balance_as_of, interest_bp
FROM debts;

DROP TABLE debts;
ALTER TABLE debts_new RENAME TO debts;
