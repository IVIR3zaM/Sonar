-- Debt flag on categories (SPEC.md §13 Debt categories).
--
-- A `fixed` category flagged `debt` holds loan and installment payments; its
-- recurring payments become draft debts on the Debts page. Only the seeded
-- 'Loans & Installments' is flagged, and only if the owner has not renamed or
-- regrouped it: hand-entered categories must survive upgrades (SPEC.md §3).
ALTER TABLE categories ADD COLUMN debt INTEGER NOT NULL DEFAULT 0 CHECK (debt IN (0, 1));

UPDATE categories SET debt = 1 WHERE name = 'Loans & Installments' AND type = 'fixed';
