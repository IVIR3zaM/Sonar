-- Draft debts (SPEC.md §13 Draft debts).
--
-- One row per recurring payment in a debt category that got a draft. An open
-- draft holds no hand-entered data: its prefill is computed from the payment
-- on every read. A completed row stays so that payment never gets a draft
-- again, even after the debt it became is deleted.
CREATE TABLE debt_drafts (
    id INTEGER PRIMARY KEY,
    detection_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'completed'))
);
