-- A free-text note on a recurring payment (what it is for), shown under its name.
-- NULL means no description; sync_detected never writes this column.
ALTER TABLE recurring_payments ADD COLUMN description TEXT;
