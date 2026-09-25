-- Categories and their ordered rules, moved from categories.toml into the DB (SPEC.md §5, §13).
--
-- `categories` replaces the TOML `[[category]]` tables; `category_rules` replaces
-- the ordered `[[rule]]` tables and matches every field of categorize.Rule, with
-- regexes stored as their source text (re-compiled by taxonomy_store on load).
-- `position` is 1-based and kept contiguous by taxonomy_store, since rules are
-- tried in order and the first match wins. Hand-entered categories and rules
-- must survive upgrades (SPEC.md §3), so this seeds only the generic taxonomy
-- below, with no rules: the owner (or Claude Code, through the Categories API)
-- adds rules afterwards.
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name <> ''),
    type TEXT NOT NULL CHECK (type IN ('income', 'transfer', 'fixed', 'lights_on', 'occasional'))
);

CREATE TABLE category_rules (
    id INTEGER PRIMARY KEY,
    position INTEGER NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    counterparty TEXT,
    counterparty_regex TEXT,
    purpose TEXT,
    purpose_regex TEXT,
    sign TEXT CHECK (sign IN ('debit', 'credit')),
    iban TEXT,
    creditor_id TEXT,
    min_amount_cents INTEGER,
    max_amount_cents INTEGER
);

INSERT INTO categories (name, type) VALUES
    ('Salary', 'income'),
    ('Other income', 'income'),
    ('Own transfers', 'transfer'),
    ('Housing', 'fixed'),
    ('Utilities', 'fixed'),
    ('Insurance', 'fixed'),
    ('Phone & Internet', 'fixed'),
    ('Subscriptions', 'fixed'),
    ('Loans & Installments', 'fixed'),
    ('Groceries', 'lights_on'),
    ('Transport', 'lights_on'),
    ('Shopping', 'lights_on'),
    ('Dining', 'occasional'),
    ('Health', 'occasional'),
    ('Fees & Taxes', 'occasional'),
    ('Education', 'occasional'),
    ('Donations', 'occasional');
