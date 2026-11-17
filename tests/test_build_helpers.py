"""Pure helpers in pun.build: calendar (F1, holidays), unit conversion, day blocks."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from pun import build as B

TZ = "Europe/Rome"


# ------------------------------------------------------------------ windows

@pytest.mark.parametrize("hours, expected", [
    ([0, 1, 2, 3, 4, 21, 22, 23], [[0, 5], [21, 24]]),
    ([23, 0, 4, 1, 22, 2, 21, 3], [[0, 5], [21, 24]]),  # unsorted input
    ([7], [[7, 8]]),
    ([3, 9], [[3, 4], [9, 10]]),
    ([], []),
])
def test_windows(hours, expected):
    assert B.windows(hours) == expected


# ------------------------------------------------------------------ calendar

@pytest.mark.parametrize("year, easter", [
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
])
def test_easter(year, easter):
    assert B._easter(year) == easter


def test_holidays_it_2026():
    h = B.holidays_it(2026)
    assert date(2026, 4, 6) in h  # Pasquetta
    for m, d in [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]:
        assert date(2026, m, d) in h
    assert date(2026, 11, 18) not in h
    assert len(h) == 11


def test_holidays_it_pasquetta_2025():
    assert date(2025, 4, 21) in B.holidays_it(2025)


def ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s, tz=TZ)


@pytest.mark.parametrize("when, expected", [
    ("2026-11-18 10:00", True),   # Wednesday, working hours
    ("2026-11-18 19:00", False),  # Wednesday, 19:00 is already F2
    ("2026-11-18 18:59", True),
    ("2026-11-21 10:00", False),  # Saturday
    ("2026-11-22 10:00", False),  # Sunday
    ("2026-12-08 10:00", False),  # Immacolata (Tuesday holiday)
    ("2026-04-06 10:00", False),  # Pasquetta (Monday)
    ("2026-11-16 08:00", True),   # Monday 08:00
    ("2026-11-16 07:00", False),  # Monday 07:00
])
def test_is_f1(when, expected):
    assert B.is_f1(ts(when)) is expected


def test_calendar_fixtures_are_the_intended_weekdays():
    assert ts("2026-11-18").weekday() == 2
    assert ts("2026-11-21").weekday() == 5
    assert ts("2026-11-16").weekday() == 0
    assert ts("2026-12-08").weekday() == 1


# ------------------------------------------------------------------ kwh

def test_kwh_scalar():
    assert B.kwh(123.456) == 0.1235
    assert B.kwh(np.float64(100)) == 0.1
    assert isinstance(B.kwh(np.float64(100)), float)


@pytest.mark.parametrize("container", [list, tuple, np.array, pd.Series])
def test_kwh_sequence(container):
    out = B.kwh(container([100.0, 242.09764, 0]))
    assert out == [0.1, 0.2421, 0.0]
    assert all(isinstance(v, float) for v in out)


# ------------------------------------------------------------------ day_block

def test_day_block_without_band(day_series):
    b = B.day_block(day_series, "actual")
    assert b["date"] == "2026-11-18"
    assert b["kind"] == "actual"
    assert len(b["hours"]) == 24
    assert b["hours"][0] == 0.06
    assert b["mean"] == B.kwh(day_series.mean())
    assert b["cheap"] == [[0, 5], [23, 24]]
    assert b["dear"] == [[16, 22]]
    assert b["min"] == {"v": 0.05, "h": 2}
    assert b["max"] == {"v": 0.16, "h": 18}
    assert "q05" not in b and "band" not in b["min"]


def test_day_block_with_band(day_series):
    band = pd.DataFrame({"q05": day_series - 10, "q50": day_series, "q95": day_series + 10})
    # extra rows outside the day must be ignored (band.loc[values.index])
    extra = band.copy()
    extra.index = extra.index + pd.Timedelta(days=1)
    b = B.day_block(day_series, "forecast", pd.concat([band, extra]))
    assert b["kind"] == "forecast"
    assert len(b["q05"]) == len(b["q95"]) == 24
    assert b["q05"][0] == 0.05 and b["q95"][0] == 0.07
    assert b["min"]["band"] == [0.04, 0.06]
    assert b["max"]["band"] == [0.15, 0.17]


def test_day_block_dst_end_day_has_no_overlapping_windows():
    # regressione: nel giorno di 25 ore l'ora locale 02 compare due volte
    idx = pd.date_range(pd.Timestamp("2025-10-26", tz=TZ).tz_convert("UTC"), periods=25,
                        freq="h").tz_convert(TZ)
    v = np.full(25, 100.0)
    v[:6] = [50, 49, 48, 47, 46, 45]  # cheapest: the night hours incl. both 02:00
    b = B.day_block(pd.Series(v, index=idx), "actual")
    flat = [h for a, z in b["cheap"] for h in range(a, z)]
    assert len(flat) == len(set(flat)), b["cheap"]
