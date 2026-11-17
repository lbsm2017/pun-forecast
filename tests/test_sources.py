"""sources.gme_pun: parsing of the GME 'Prezzi' XML files (offline, synthetic files)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pun import sources as S

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


def _assert_strictly_hourly(s: pd.Series, n: int):
    assert len(s) == n
    assert s.index.is_unique
    assert s.index.is_monotonic_increasing
    assert (s.index.tz_convert("UTC").to_series().diff().dropna() == pd.Timedelta(hours=1)).all()


def test_comma_decimals_and_timezone(write_gme):
    folder = write_gme("20261103", 24, base=242)
    s = S.gme_pun(folder)
    assert str(s.index.tz) == "Europe/Rome"
    assert s.dtype == "float64"
    # Ora 1 -> PUN "243,000000"; check the comma was read as decimal separator
    assert s.iloc[0] == pytest.approx(243.0)
    assert s.iloc[-1] == pytest.approx(266.0)


def test_comma_decimal_fraction(tmp_path):
    xml = ('<NewDataSet><Prezzi><Data>20261103</Data><Mercato>MGP</Mercato><Ora>1</Ora>'
           '<PUN>242,097640</PUN></Prezzi></NewDataSet>')
    (tmp_path / "20261103MGPPrezzi.xml").write_text(xml, encoding="utf-8")
    s = S.gme_pun(tmp_path)
    assert s.iloc[0] == pytest.approx(242.09764)


def test_normal_day_has_24_consecutive_hours(write_gme):
    s = S.gme_pun(write_gme("20261103", 24))
    _assert_strictly_hourly(s, 24)
    assert s.index[0] == pd.Timestamp("2026-11-03 00:00", tz="Europe/Rome")
    assert s.index[-1] == pd.Timestamp("2026-11-03 23:00", tz="Europe/Rome")
    assert list(s.index.hour) == list(range(24))


def test_dst_end_day_has_25_distinct_hours(write_gme):
    s = S.gme_pun(write_gme("20251026", 25))
    _assert_strictly_hourly(s, 25)
    assert set(s.index.date) == {pd.Timestamp("2025-10-26").date()}
    # local 02:00 occurs twice (CEST then CET)
    assert list(s.index.hour).count(2) == 2


def test_dst_start_day_has_23_hours(write_gme):
    s = S.gme_pun(write_gme("20260329", 23))
    _assert_strictly_hourly(s, 23)
    assert set(s.index.date) == {pd.Timestamp("2026-03-29").date()}
    assert 2 not in set(s.index.hour)  # 02:00 does not exist that day


def test_several_days_are_contiguous_across_dst(write_gme):
    write_gme("20251025", 24)
    write_gme("20251026", 25)
    folder = write_gme("20251027", 24)
    s = S.gme_pun(folder)
    _assert_strictly_hourly(s, 24 + 25 + 24)


def test_zip_files_are_read(write_gme):
    write_gme("20261103", 24, zip_name="MGP_Prezzi.zip")
    folder = write_gme("20261104", 24, zip_name="MGP_Prezzi.zip")
    s = S.gme_pun(folder)
    _assert_strictly_hourly(s, 48)


def test_quarter_hour_files_are_ignored(write_gme):
    write_gme("20261103", 24)
    write_gme("20261104", 96, base=999, suffix="MGPPrezzi15.xml")
    folder = write_gme("20261105", 96, base=999, suffix="MGPPrezzi15.xml", zip_name="q.zip")
    s = S.gme_pun(folder)
    assert len(s) == 24
    assert (s < 999).all()


def test_empty_folder_returns_empty_series(tmp_path):
    s = S.gme_pun(tmp_path)
    assert s.empty


@pytest.mark.skipif(not SAMPLES.exists(), reason="data/samples not available")
def test_local_samples():
    s = S.gme_pun(SAMPLES)
    assert len(s) == 360
    assert s.index[0] == pd.Timestamp("2026-11-03 00:00", tz="Europe/Rome")
    assert s.index[-1] == pd.Timestamp("2026-11-17 23:00", tz="Europe/Rome")
    assert s.index.is_unique and s.index.is_monotonic_increasing
    assert s.notna().all()
