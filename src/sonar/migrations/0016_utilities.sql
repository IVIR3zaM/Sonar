-- Energy tables become Utilities tables and gain water (SPEC.md §13 Utilities).
--
-- Same rows and ids as the energy_* tables, under utility_* names. Meters may be
-- water; a period gains an advance mode (flexible, or a schedule of dates in
-- utility_advance_dates), settlement debit days and, for water, a drinking and a
-- wastewater charge (price, base fee, VAT) with the gas/electricity price and
-- base fee left NULL. expected_kwh becomes expected_usage (kWh or m3).
CREATE TABLE utility_meters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE CHECK (name <> ''),
    kind TEXT NOT NULL CHECK (kind IN ('gas', 'electricity', 'water'))
);

CREATE TABLE utility_readings (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES utility_meters(id),
    reading_date TEXT NOT NULL,
    value_milli INTEGER NOT NULL,
    UNIQUE (meter_id, reading_date)
);

CREATE TABLE utility_exchanges (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES utility_meters(id),
    exchange_date TEXT NOT NULL,
    old_final_milli INTEGER NOT NULL,
    new_start_milli INTEGER NOT NULL,
    UNIQUE (meter_id, exchange_date)
);

CREATE TABLE utility_periods (
    id INTEGER PRIMARY KEY,
    meter_id INTEGER NOT NULL REFERENCES utility_meters(id),
    start_date TEXT NOT NULL,
    settlement_date TEXT NOT NULL,
    base_fee_cents INTEGER,
    unit_price_micro INTEGER,
    state_factor_e4 INTEGER,
    calorific_value_e4 INTEGER,
    advance_cents INTEGER NOT NULL,
    expected_usage INTEGER NOT NULL,
    category_id INTEGER,
    settled_cents INTEGER,
    advance_mode TEXT NOT NULL DEFAULT 'flexible' CHECK (advance_mode IN ('flexible', 'schedule')),
    settlement_debit_days INTEGER NOT NULL DEFAULT 0,
    drinking_price_micro INTEGER,
    drinking_base_fee_cents INTEGER,
    drinking_vat_percent INTEGER,
    wastewater_price_micro INTEGER,
    wastewater_base_fee_cents INTEGER,
    wastewater_vat_percent INTEGER
);

CREATE TABLE utility_advance_dates (
    id INTEGER PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES utility_periods(id),
    due_date TEXT NOT NULL,
    UNIQUE (period_id, due_date)
);

INSERT INTO utility_meters (id, name, kind)
SELECT id, name, kind FROM energy_meters;

INSERT INTO utility_readings (id, meter_id, reading_date, value_milli)
SELECT id, meter_id, reading_date, value_milli FROM energy_readings;

INSERT INTO utility_exchanges (id, meter_id, exchange_date, old_final_milli, new_start_milli)
SELECT id, meter_id, exchange_date, old_final_milli, new_start_milli FROM energy_exchanges;

INSERT INTO utility_periods (
    id, meter_id, start_date, settlement_date, base_fee_cents, unit_price_micro,
    state_factor_e4, calorific_value_e4, advance_cents, expected_usage, category_id,
    settled_cents
)
SELECT
    id, meter_id, start_date, settlement_date, base_fee_cents, unit_price_micro,
    state_factor_e4, calorific_value_e4, advance_cents, expected_kwh, category_id,
    settled_cents
FROM energy_periods;

DROP TABLE energy_periods;
DROP TABLE energy_exchanges;
DROP TABLE energy_readings;
DROP TABLE energy_meters;
