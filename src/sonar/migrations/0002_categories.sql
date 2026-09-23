-- Add categorization column to transactions (SPEC.md §5).
--
-- NULL = uncategorized. The category name refers to categories.toml.
-- Rules are re-applied on every import and at startup, so rule changes
-- take effect everywhere.
ALTER TABLE transactions ADD COLUMN category TEXT;
