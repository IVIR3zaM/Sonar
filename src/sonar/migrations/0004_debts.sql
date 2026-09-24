-- Installments and loans (SPEC.md §7).
--
-- One model with kind (installment or loan) and hand-entered data that must
-- survive upgrades. Each debt has a match rule linking it to real bank
-- transactions via counterparty or mandate reference. An installment tracks
-- paid so far, remaining, payments remaining and end date. A loan tracks
-- the projected balance and payoff date using amortization (with optional
-- interest rate) or linear projection.
CREATE TABLE debts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('installment', 'loan')),
    name TEXT NOT NULL CHECK (name <> ''),
    rate_cents INTEGER NOT NULL CHECK (rate_cents > 0),
    match_field TEXT NOT NULL CHECK (match_field IN ('counterparty', 'mandate')),
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
