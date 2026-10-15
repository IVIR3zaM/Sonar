-- The amount a billing period was finally settled for, signed as on the bill
-- (negative = back-payment, positive = refund); NULL = not settled or unknown
-- (SPEC.md §13 Energy billing cycle).
ALTER TABLE energy_periods ADD COLUMN settled_cents INTEGER;
