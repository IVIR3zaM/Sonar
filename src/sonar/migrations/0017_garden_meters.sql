-- Garden water sub-meters (SPEC.md §13 Utilities).
--
-- A garden meter links to its main water meter; a water period may carry a garden
-- fee; utility_garden_zeroed holds the intervals of a garden meter whose usage the
-- owner zeroed after a conflict with the main meter. Existing rows keep NULLs.
ALTER TABLE utility_meters ADD COLUMN main_meter_id INTEGER REFERENCES utility_meters(id);

ALTER TABLE utility_periods ADD COLUMN garden_fee_cents INTEGER;

CREATE TABLE utility_garden_zeroed (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES utility_meters(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    UNIQUE (meter_id, start_date, end_date)
);
