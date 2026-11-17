"""pun.backtest on synthetic series, with baseline models only (no Timestral)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pun import backtest as BT

TZ = "Europe/Rome"
HOURLY_KEYS = {"mae_1", "mae_7", "mae_30", "daily_mae_30", "coverage90", "hit6", "n", "seconds"}
DAILY_KEYS = {"mae_30", "mae_90", "month1_mae", "month2_mae", "month3_mae", "coverage90", "n", "seconds"}


def hourly(start: str, periods: int, values=None) -> pd.Series:
    idx = pd.date_range(pd.Timestamp(start, tz=TZ).tz_convert("UTC"), periods=periods,
                        freq="h").tz_convert(TZ)
    v = np.arange(periods, dtype=float) if values is None else values
    return pd.Series(v, index=idx)


# ------------------------------------------------------------ regular_hourly

def test_regular_hourly_fills_small_gap_and_keeps_tz():
    s = hourly("2026-11-01", 48)
    holed = s.drop(s.index[10:13])
    out = BT.regular_hourly(holed)
    assert str(out.index.tz) == TZ
    assert out.index.equals(s.index)
    # linear series: interpolation restores the exact values
    np.testing.assert_allclose(out.to_numpy(), s.to_numpy())


@pytest.mark.parametrize("start", ["2025-10-24", "2026-03-27"])
def test_regular_hourly_across_dst(start):
    s = hourly(start, 24 * 5)
    holed = s.drop(s.index[[30, 50, 51, 70]])  # gaps around the DST change
    out = BT.regular_hourly(holed)
    expected = pd.date_range(s.index[0].tz_convert("UTC"), s.index[-1].tz_convert("UTC"),
                             freq="h").tz_convert(TZ)
    assert out.index.equals(expected)
    assert out.index.is_unique
    assert out.notna().all()
    np.testing.assert_allclose(out.to_numpy(), s.to_numpy())


# ---------------------------------------------------------------- daily_mean

def test_daily_mean_one_value_per_civil_day_including_dst():
    # 2025-10-25 (24h), 2025-10-26 (25h), 2025-10-27 (24h)
    s = hourly("2025-10-25", 24 + 25 + 24)
    s[:] = np.r_[np.full(24, 10.0), np.full(25, 20.0), np.full(24, 30.0)]
    d = BT.daily_mean(s)
    assert d.index.tz is None
    assert list(d.index) == list(pd.date_range("2025-10-25", periods=3, freq="D"))
    assert d.tolist() == [10.0, 20.0, 30.0]


def test_daily_mean_23_hour_day():
    s = hourly("2026-03-28", 24 + 23 + 24)
    s[:] = np.r_[np.full(24, 1.0), np.arange(23, dtype=float), np.full(24, 3.0)]
    d = BT.daily_mean(s)
    assert len(d) == 3
    assert d.index.freqstr == "D"
    assert d.loc["2026-03-29"] == pytest.approx(np.arange(23).mean())


# ---------------------------------------------------------------- _cheap_hit

def test_cheap_hit():
    a = np.arange(24, dtype=float)
    assert BT._cheap_hit(a, a) == 1.0
    assert BT._cheap_hit(a, a[::-1]) == 0.0
    b = a.copy()
    b[[0, 1, 2]] = 100  # 3 of the 6 cheapest hours move to the top
    assert BT._cheap_hit(a, b) == pytest.approx(0.5)


# ------------------------------------------------------------ hourly_origins

def test_hourly_origins(hourly_prices):
    s = hourly_prices
    ends = BT.hourly_origins(s, n=5, step_days=7)
    assert len(ends) == 5
    assert ends == sorted(ends)
    for e in ends:
        assert s.index[e + 1].hour == 0 and s.index[e + 1].minute == 0
        assert len(s) - (e + 1) >= BT.H30
    gaps = np.diff([s.index[e + 1].normalize().tz_localize(None) for e in ends])
    assert all(g == pd.Timedelta(days=7) for g in gaps)


# ---------------------------------------------------------------- run_hourly

def _check_common(res: dict, models, keys):
    assert set(res) == set(models)
    for m in models:
        r = res[m]
        assert set(r) == keys, m
        assert r["n"] > 0
        assert 0.0 <= r["coverage90"] <= 1.0
        for k, v in r.items():
            assert np.isfinite(v), (m, k)


def test_run_hourly_baselines(hourly_prices):
    models = ["naive-week", "mean-4w"]
    res = BT.run_hourly(hourly_prices, models, n_origins=4, step_days=7)
    _check_common(res, models, HOURLY_KEYS)
    for m in models:
        assert res[m]["n"] == 4
        assert 0.0 <= res[m]["hit6"] <= 1.0
        assert res[m]["mae_1"] >= 0


def test_run_hourly_naive_week_is_exact_on_weekly_series(weekly_periodic):
    res = BT.run_hourly(weekly_periodic, ["naive-week"], n_origins=3, min_context=24 * 60)
    r = res["naive-week"]
    assert r["n"] == 3
    assert r["mae_30"] == pytest.approx(0, abs=1e-6)
    assert r["hit6"] == 1.0


# ----------------------------------------------------------------- run_daily

def test_run_daily_baselines(daily_prices):
    models = ["flat-28d", "seasonal-ratio"]
    res = BT.run_daily(daily_prices, models, n_origins=4, step_days=14)
    _check_common(res, models, DAILY_KEYS)
    for m in models:
        assert res[m]["n"] == 4
        assert res[m]["mae_90"] >= 0
    # the yearly cycle is strong: the seasonal model must beat the flat one
    assert res["seasonal-ratio"]["mae_90"] < res["flat-28d"]["mae_90"]


# ---------------------------------------------------------------------- pick

def test_pick_returns_minimum():
    results = {"a": {"mae_7": 3.0, "mae_90": 1.0}, "b": {"mae_7": 2.0, "mae_90": 5.0},
               "c": {"mae_7": 4.0, "mae_90": 2.0}}
    assert BT.pick(results, "mae_7") == "b"
    assert BT.pick(results, "mae_90") == "a"
