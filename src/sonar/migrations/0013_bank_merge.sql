-- One booking from a CSV and from the bank sync is stored once (SPEC.md §13 Bank sync).
--
-- `entry_reference` is the bank's id for a synced booking; a refetch with a stored
-- reference is a duplicate. `merged` is 1 once a row has been matched with the other
-- source, so it never pairs again.
ALTER TABLE transactions ADD COLUMN entry_reference TEXT;
ALTER TABLE transactions ADD COLUMN merged INTEGER NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX transactions_entry_reference
    ON transactions (entry_reference) WHERE entry_reference IS NOT NULL;
