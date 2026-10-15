-- Energy meters, readings, exchanges and billing periods (SPEC.md §13 Energy).
--
-- Readings and values are integer thousandths of the meter unit, prices and
-- factors scaled integers, money integer cents. A meter has at most one reading
-- and one exchange per date. A period's category is stored by id; a deleted
-- category leaves a dangling id that reads back as no category.
CREATE TABLE energy_meters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name <> ''),
    kind TEXT NOT NULL CHECK (kind IN ('gas', 'electricity'))
);

CREATE TABLE energy_readings (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES energy_meters(id),
    reading_date TEXT NOT NULL,
    value_milli INTEGER NOT NULL,
    UNIQUE (meter_id, reading_date)
);

CREATE TABLE energy_exchanges (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES energy_meters(id),
    exchange_date TEXT NOT NULL,
    old_final_milli INTEGER NOT NULL,
    new_start_milli INTEGER NOT NULL,
    UNIQUE (meter_id, exchange_date)
);

CREATE TABLE energy_periods (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES energy_meters(id),
    start_date TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    base_fee_cents INTEGER NOT NULL,
    unit_price_micro INTEGER NOT NULL,
    state_factor_e4 INTEGER,
    calorific_value_e4 INTEGER,
    advance_cents INTEGER NOT NULL,
    expected_kwh INTEGER NOT NULL,
    category_id INTEGER
);
