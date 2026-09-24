-- Settings for the household: salary day, overdraft limit and manual balance override (SPEC.md §8, §4, §9).
--
-- Hand-entered settings must survive upgrades (SPEC.md §3), so they live in their
-- own table with no foreign key dependencies. A missing row means the setting is not
-- yet configured. The manual balance reuses balances with source 'manual' from
-- 0001_import.sql, so there is no separate balance table here.
CREATE TABLE settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    salary_day INTEGER NOT NULL CHECK (salary_day BETWEEN 1 AND 31),
    -- overdraft_limit_cents has no DEFAULT because when no settings row exists yet,
    -- a column DEFAULT never applies. Instead, the -50000 default lives only in code
    -- (settings_store.DEFAULT_OVERDRAFT_LIMIT_CENTS) and is written together with
    -- salary_day on every save, which keeps one source of truth.
    overdraft_limit_cents INTEGER NOT NULL CHECK (overdraft_limit_cents <= 0)
);
