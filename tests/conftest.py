"""Shared fixtures: synthetic price series and a GME XML writer.

Everything here is offline and deterministic (fixed RNG seeds).
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

TZ = "Europe/Rome"

GME_HEADER = """<?xml version="1.0" standalone="yes"?>
<NewDataSet>
  <xs:schema id="NewDataSet" xmlns="" xmlns:xs="http://www.w3.org/2001/XMLSchema">
    <xs:element name="NewDataSet"><xs:complexType><xs:choice>
      <xs:element name="Prezzi" />
    </xs:choice></xs:complexType></xs:element>
  </xs:schema>
"""


def gme_xml(day: str, n_hours: int, base: float = 100.0) -> str:
    """GME 'Prezzi' XML for one day (YYYYMMDD) with Ora 1..n_hours, comma decimals.

    The PUN of hour k is ``base + k + 0.097640`` so values are easy to check.
    """
    rows = []
    for ora in range(1, n_hours + 1):
        pun = f"{base + ora:.6f}".replace(".", ",")
        rows.append(
            f"  <Prezzi><Data>{day}</Data><Mercato>MGP</Mercato><Ora>{ora}</Ora>"
            f"<PUN>{pun}</PUN><NORD>{pun}</NORD></Prezzi>\n"
        )
    return GME_HEADER + "".join(rows) + "</NewDataSet>\n"


@pytest.fixture
def write_gme(tmp_path: Path):
    """Write a GME day file into tmp_path (or into a zip); returns the folder."""

    def _write(day: str, n_hours: int, base: float = 100.0, zip_name: str | None = None,
               suffix: str = "MGPPrezzi.xml") -> Path:
        name = f"{day}{suffix}"
        text = gme_xml(day, n_hours, base)
        if zip_name:
            with zipfile.ZipFile(tmp_path / zip_name, "a") as z:
                z.writestr(name, text)
        else:
            (tmp_path / name).write_text(text, encoding="utf-8")
        return tmp_path

    return _write


def _hourly_index(start: str, periods: int) -> pd.DatetimeIndex:
    """Regular hourly index in UTC, shown in Europe/Rome (crosses DST correctly)."""
    return pd.date_range(pd.Timestamp(start, tz=TZ).tz_convert("UTC"), periods=periods,
                         freq="h").tz_convert(TZ)


@pytest.fixture(scope="session")
def hourly_prices() -> pd.Series:
    """~2 years of hourly prices (Europe/Rome) with daily + weekly seasonality and noise."""
    rng = np.random.default_rng(42)
    idx = _hourly_index("2024-01-01", 24 * 730)
    t = np.arange(len(idx))
    y = (100 + 20 * np.sin(2 * np.pi * t / 24) + 10 * np.sin(2 * np.pi * t / 168)
         + rng.normal(0, 3, len(idx)))
    return pd.Series(y, index=idx, name="price")


@pytest.fixture(scope="session")
def weekly_periodic() -> pd.Series:
    """Noise-free hourly series with an exact 168-hour period (crosses 2025-10-26)."""
    idx = _hourly_index("2025-06-01", 24 * 200)
    t = np.arange(len(idx))
    y = 100 + 10 * np.sin(2 * np.pi * t / 168) + 5 * np.sin(2 * np.pi * t / 24)
    return pd.Series(y, index=idx)


@pytest.fixture(scope="session")
def daily_prices() -> pd.Series:
    """~4.5 years of daily means (naive index) with yearly + weekly seasonality and noise.

    run_daily needs more than 3 years of history before the first origin.
    """
    rng = np.random.default_rng(7)
    idx = pd.date_range("2021-01-01", periods=365 * 4 + 180, freq="D")
    t = np.arange(len(idx))
    y = (100 + 25 * np.sin(2 * np.pi * t / 365.25) + 8 * np.sin(2 * np.pi * t / 7)
         + rng.normal(0, 4, len(idx)))
    return pd.Series(y, index=idx, name="daily")


@pytest.fixture
def day_series() -> pd.Series:
    """24 hourly prices for a plain weekday: cheap at night, dear in the evening."""
    idx = pd.date_range("2026-11-18 00:00", periods=24, freq="h", tz=TZ)
    v = np.array([60, 55, 50, 52, 58, 70, 90, 110, 120, 115, 100, 95,
                  90, 88, 92, 100, 130, 150, 160, 155, 140, 125, 80, 65], dtype=float)
    return pd.Series(v, index=idx)
