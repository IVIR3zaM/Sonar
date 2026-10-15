"""Tests for the energy DB shell (SPEC §13 Energy): round trips, validation, deletes."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest

from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.energy.model import BillingPeriod, Exchange, FieldError, Meter, Reading
from sonar.energy.store import (
    EnergyNotFound,
    MeterNotEmpty,
    add_exchange,
    add_meter,
    add_period,
    add_reading,
    delete_exchange,
    delete_meter,
    delete_period,
    delete_reading,
    list_exchanges,
    list_meters,
    list_periods,
    list_readings,
    meter_of_exchange,
    meter_of_period,
    meter_of_reading,
    rename_meter,
    update_exchange,
    update_period,
    update_reading,
)

TABLES = ("energy_meters", "energy_readings", "energy_exchanges", "energy_periods")


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _snapshot(conn: sqlite3.Connection) -> list[list[tuple]]:
    return [conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in TABLES]


def _gas(conn: sqlite3.Connection) -> int:
    return add_meter(conn, Meter("Gas", "gas"))


def _period(**changes) -> BillingPeriod:
    period = BillingPeriod(
        start_date=date(2026, 1, 1),
        settlement_date=date(2026, 12, 31),
        base_fee_cents=1200,
        unit_price_micro=80_000,
        state_factor_e4=9_500,
        calorific_value_e4=110_000,
        advance_cents=9_000,
        expected_kwh=15_000,
        category=None,
    )
    return replace(period, **changes)


def test_added_meter_and_reading_are_listed(conn):
    meter_id = _gas(conn)

    reading_id = add_reading(conn, meter_id, Reading(date(2026, 1, 1), 1_000_000))

    assert [(m.id, m.item) for m in list_meters(conn)] == [(meter_id, Meter("Gas", "gas"))]
    stored = list_readings(conn, meter_id)
    assert [(r.id, r.item) for r in stored] == [(reading_id, Reading(date(2026, 1, 1), 1_000_000))]


def test_meters_are_listed_by_name_and_renamed(conn):
    electricity = add_meter(conn, Meter("Power", "electricity"))
    gas = _gas(conn)

    assert [m.id for m in list_meters(conn)] == [gas, electricity]
    rename_meter(conn, gas, "Heating")
    assert [m.item.name for m in list_meters(conn)] == ["Heating", "Power"]


def test_meter_names_are_unique_and_not_blank(conn):
    _gas(conn)

    with pytest.raises(FieldError) as duplicate:
        add_meter(conn, Meter("Gas", "electricity"))
    with pytest.raises(FieldError) as renamed:
        rename_meter(conn, add_meter(conn, Meter("Power", "electricity")), "Gas")
    with pytest.raises(FieldError) as blank:
        rename_meter(conn, 1, " ")

    assert duplicate.value.field == "name"
    assert renamed.value.field == "name"
    assert blank.value.field == "name"
    assert len(list_meters(conn)) == 2


def test_readings_are_listed_by_date_and_update_and_delete_round_trip(conn):
    meter = _gas(conn)
    later = add_reading(conn, meter, Reading(date(2026, 3, 1), 1_300_000))
    earlier = add_reading(conn, meter, Reading(date(2026, 2, 1), 1_100_000))

    assert [r.id for r in list_readings(conn, meter)] == [earlier, later]
    update_reading(conn, later, Reading(date(2026, 3, 5), 1_400_000))
    assert list_readings(conn, meter)[1].item == Reading(date(2026, 3, 5), 1_400_000)
    delete_reading(conn, earlier)
    assert [r.id for r in list_readings(conn, meter)] == [later]


def test_exchanges_round_trip(conn):
    meter = _gas(conn)
    add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000))

    exchange = add_exchange(conn, meter, Exchange(date(2026, 2, 1), 1_200_000, 5_000))
    assert [(e.id, e.item) for e in list_exchanges(conn, meter)] == [
        (exchange, Exchange(date(2026, 2, 1), 1_200_000, 5_000))
    ]
    update_exchange(conn, exchange, Exchange(date(2026, 2, 2), 1_250_000, 0))
    assert list_exchanges(conn, meter)[0].item == Exchange(date(2026, 2, 2), 1_250_000, 0)
    delete_exchange(conn, exchange)
    assert list_exchanges(conn, meter) == []


def test_periods_round_trip_and_read_the_category_by_name(conn):
    meter = _gas(conn)
    conn.execute("INSERT INTO categories (name, type) VALUES ('Gas bill', 'fixed')")

    period = add_period(conn, meter, _period(category="Gas bill"))
    assert [(p.id, p.item) for p in list_periods(conn, meter)] == [
        (period, _period(category="Gas bill"))
    ]
    update_period(conn, period, _period(advance_cents=9_500, category=None))
    assert list_periods(conn, meter)[0].item == _period(advance_cents=9_500)
    delete_period(conn, period)
    assert list_periods(conn, meter) == []


@pytest.mark.parametrize("settled", [-3169, 4200, None])
def test_settled_amount_round_trips_through_add_and_update(conn, settled):
    meter = _gas(conn)

    period = add_period(conn, meter, _period(settled_cents=settled))
    assert list_periods(conn, meter)[0].item.settled_cents == settled
    update_period(conn, period, _period(settled_cents=-27_013))
    assert list_periods(conn, meter)[0].item.settled_cents == -27_013
    update_period(conn, period, _period(settled_cents=settled))
    assert list_periods(conn, meter)[0].item.settled_cents == settled


def test_a_deleted_category_reads_back_as_none(conn):
    meter = _gas(conn)
    conn.execute("INSERT INTO categories (name, type) VALUES ('Gas bill', 'fixed')")
    add_period(conn, meter, _period(category="Gas bill"))

    conn.execute("DELETE FROM categories WHERE name = 'Gas bill'")

    assert list_periods(conn, meter)[0].item.category is None


def test_an_unknown_category_is_rejected_and_writes_nothing(conn):
    meter = _gas(conn)
    period = add_period(conn, meter, _period())
    before = _snapshot(conn)

    with pytest.raises(FieldError) as added:
        add_period(conn, meter, _period(start_date=date(2027, 1, 1), category="Nope"))
    with pytest.raises(FieldError) as updated:
        update_period(conn, period, _period(category="Nope"))

    assert added.value.field == updated.value.field == "category"
    assert _snapshot(conn) == before


def test_rejected_series_writes_leave_the_tables_unchanged(conn):
    meter = _gas(conn)
    first = add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000))
    exchange = add_exchange(conn, meter, Exchange(date(2026, 2, 1), 1_100_000, 0))
    add_reading(conn, meter, Reading(date(2026, 3, 1), 100_000))
    before = _snapshot(conn)

    rejected = [
        ("value", lambda: add_reading(conn, meter, Reading(date(2026, 4, 1), 50_000))),
        ("date", lambda: add_reading(conn, meter, Reading(date(2026, 2, 1), 5_000))),
        ("date", lambda: add_reading(conn, meter, Reading(date(2026, 1, 1), 1_000_000))),
        ("date", lambda: add_exchange(conn, meter, Exchange(date(2026, 1, 1), 1_000_000, 0))),
        ("value", lambda: update_reading(conn, first, Reading(date(2026, 1, 1), 2_000_000))),
        ("date", lambda: update_exchange(conn, exchange, Exchange(date(2026, 3, 1), 1, 0))),
        ("value", lambda: delete_exchange(conn, exchange)),
    ]
    for field, write in rejected:
        with pytest.raises(FieldError) as error:
            write()
        assert error.value.field == field
        assert _snapshot(conn) == before


def test_an_overlapping_or_invalid_period_is_rejected_and_writes_nothing(conn):
    meter = _gas(conn)
    add_period(conn, meter, _period(settlement_date=date(2026, 6, 30)))
    second = add_period(conn, meter, _period(start_date=date(2026, 7, 1)))
    before = _snapshot(conn)

    with pytest.raises(FieldError) as overlap:
        add_period(conn, meter, _period(start_date=date(2026, 6, 30)))
    with pytest.raises(FieldError) as moved:
        update_period(conn, second, _period(start_date=date(2026, 6, 1)))
    with pytest.raises(FieldError) as invalid:
        add_period(
            conn,
            meter,
            _period(
                start_date=date(2028, 1, 1),
                settlement_date=date(2028, 12, 31),
                state_factor_e4=None,
            ),
        )

    assert overlap.value.field == moved.value.field == "start_date"
    assert invalid.value.field == "state_factor_e4"
    assert _snapshot(conn) == before


def test_a_period_may_be_updated_in_place(conn):
    meter = _gas(conn)
    period = add_period(conn, meter, _period())

    update_period(conn, period, _period(settlement_date=date(2026, 6, 30)))

    assert list_periods(conn, meter)[0].item.settlement_date == date(2026, 6, 30)


def test_only_an_empty_meter_can_be_deleted(conn):
    for add in (
        lambda meter: add_reading(conn, meter, Reading(date(2026, 1, 1), 0)),
        lambda meter: add_exchange(conn, meter, Exchange(date(2026, 1, 1), 0, 0)),
        lambda meter: add_period(conn, meter, _period()),
    ):
        meter = add_meter(conn, Meter(f"Gas {len(list_meters(conn))}", "gas"))
        add(meter)
        with pytest.raises(MeterNotEmpty):
            delete_meter(conn, meter)
    empty = add_meter(conn, Meter("Empty", "gas"))

    delete_meter(conn, empty)

    assert empty not in [m.id for m in list_meters(conn)]
    assert len(list_meters(conn)) == 3


def test_unknown_ids_raise_not_found(conn):
    meter = _gas(conn)
    calls = [
        lambda: rename_meter(conn, 99, "X"),
        lambda: delete_meter(conn, 99),
        lambda: add_reading(conn, 99, Reading(date(2026, 1, 1), 0)),
        lambda: update_reading(conn, 99, Reading(date(2026, 1, 1), 0)),
        lambda: delete_reading(conn, 99),
        lambda: add_exchange(conn, 99, Exchange(date(2026, 1, 1), 0, 0)),
        lambda: update_exchange(conn, 99, Exchange(date(2026, 1, 1), 0, 0)),
        lambda: delete_exchange(conn, 99),
        lambda: add_period(conn, 99, _period()),
        lambda: update_period(conn, 99, _period()),
        lambda: delete_period(conn, 99),
        lambda: list_readings(conn, 99),
    ]
    for call in calls:
        with pytest.raises(EnergyNotFound):
            call()
    assert [m.id for m in list_meters(conn)] == [meter]


def test_electricity_period_rejects_gas_fields(conn):
    meter = add_meter(conn, Meter("Power", "electricity"))

    with pytest.raises(FieldError) as error:
        add_period(conn, meter, _period())

    assert error.value.field == "state_factor_e4"
    assert list_periods(conn, meter) == []


def test_the_meter_of_a_reading_exchange_or_period_is_found(conn):
    first = _gas(conn)
    second = add_meter(conn, Meter("Power", "electricity"))
    reading = add_reading(conn, second, Reading(date(2026, 1, 1), 1_000))
    exchange = add_exchange(conn, second, Exchange(date(2026, 2, 1), 2_000, 0))
    period = add_period(conn, first, _period())

    assert meter_of_reading(conn, reading) == second
    assert meter_of_exchange(conn, exchange) == second
    assert meter_of_period(conn, period) == first


def test_the_meter_of_a_missing_record_is_not_found(conn):
    for lookup in (meter_of_reading, meter_of_exchange, meter_of_period):
        with pytest.raises(EnergyNotFound):
            lookup(conn, 99)
