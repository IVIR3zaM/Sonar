-- Recurring payments and schedule periods (SPEC.md §6).
--
-- Each recurring_payment has a list of schedule_periods, each defining a time
-- window (from starts_on to optional until) with an amount, interval and day.
-- Foreign keys are off in db.connect, so the store must delete periods explicitly
-- when a payment is deleted. detection_key is UNIQUE but allows multiple NULLs
-- for manual entries that are not linked to detection.
CREATE TABLE recurring_payments (
    id INTEGER PRIMARY KEY,
    detection_key TEXT UNIQUE,
    name TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dismissed')),
    source TEXT NOT NULL CHECK (source IN ('detected', 'manual')),
    name_locked INTEGER NOT NULL DEFAULT 0,
    schedule_locked INTEGER NOT NULL DEFAULT 0,
    last_paid_date TEXT
);

CREATE TABLE schedule_periods (
    id INTEGER PRIMARY KEY,
    payment_id INTEGER NOT NULL REFERENCES recurring_payments(id),
    starts_on TEXT NOT NULL,
    until TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    interval_months INTEGER NOT NULL CHECK (interval_months >= 1),
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31)
);
