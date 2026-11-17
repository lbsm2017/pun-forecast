"""Baseline forecasters in pun.forecast (the Timestral entries are never called here)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pun import forecast as F

TZ = "Europe/Rome"


def assert_ordered_quantiles(fc: pd.DataFrame):
    assert list(fc.columns[:3]) == ["q05", "q50", "q95"]
    assert fc[["q05", "q50", "q95"]].notna().all().all()
    assert (fc["q05"] <= fc["q50"] + 1e-9).all()
    assert (fc["q50"] <= fc["q95"] + 1e-9).all()


def assert_hourly_after(fc: pd.DataFrame, last: pd.Timestamp, steps: int):
    idx = fc.index
    assert len(idx) == steps
    assert str(idx.tz) == TZ
    assert idx.is_unique and idx.is_monotonic_increasing
    utc = idx.tz_convert("UTC")
    assert utc[0] == last.tz_convert("UTC") + pd.Timedelta(hours=1)
    assert (utc.to_series().diff().dropna() == pd.Timedelta(hours=1)).all()


# ------------------------------------------------------------ _future_index

@pytest.mark.parametrize("day, n_local_hours", [("2026-03-29", 23), ("2025-10-26", 25)])
def test_future_index_hourly_across_dst(day, n_local_hours):
    last = pd.Timestamp(day, tz=TZ) - pd.Timedelta(hours=1)  # 23:00 of the previous day
    idx = F._future_index(last, 48, "h")
    assert len(idx) == 48 and idx.is_unique and idx.is_monotonic_increasing
    assert str(idx.tz) == TZ
    assert idx[0] == pd.Timestamp(day, tz=TZ)
    assert (np.diff(idx.tz_convert("UTC").asi8) == np.diff(idx.tz_convert("UTC").asi8)[0]).all()
    assert (idx.date == pd.Timestamp(day).date()).sum() == n_local_hours


def test_future_index_daily():
    idx = F._future_index(pd.Timestamp("2026-11-17"), 3, "D")
    assert list(idx) == list(pd.date_range("2026-11-18", periods=3, freq="D"))
    assert idx.tz is None


# ------------------------------------------------------------- hourly models

@pytest.fixture
def hourly_history(hourly_prices):
    """History ending at the last hour of 2025-10-24: the forecast crosses 2025-10-26."""
    end = pd.Timestamp("2025-10-25", tz=TZ)
    return hourly_prices[hourly_prices.index < end]


@pytest.mark.parametrize("model", [F.naive_week, F.mean_4w])
def test_hourly_baselines_across_dst(model, hourly_history):
    steps = 31 * 24
    fc = model(hourly_history, steps)
    assert_hourly_after(fc, hourly_history.index[-1], steps)
    assert_ordered_quantiles(fc)
    # the forecast covers 2025-10-26 with its 25 local hours
    assert (fc.index.date == pd.Timestamp("2025-10-26").date()).sum() == 25


def test_hourly_registry_contains_baselines():
    assert F.HOURLY["naive-week"] is F.naive_week
    assert F.HOURLY["mean-4w"] is F.mean_4w
    assert F.DAILY["flat-28d"] is F.flat_28d
    assert F.DAILY["seasonal-ratio"] is F.seasonal_ratio
    assert F.BASELINES == {"naive-week", "mean-4w", "flat-28d", "seasonal-ratio"}


def test_naive_week_repeats_last_week(hourly_history):
    fc = F.naive_week(hourly_history, 200)
    last_week = hourly_history.to_numpy()[-168:]
    np.testing.assert_allclose(fc["q50"].to_numpy()[:168], last_week)
    np.testing.assert_allclose(fc["q50"].to_numpy()[168:], last_week[:32])


def test_mean_4w_point_is_4_week_profile(hourly_history):
    fc = F.mean_4w(hourly_history, 168)
    expected = hourly_history.to_numpy()[-672:].reshape(4, 168).mean(axis=0)
    np.testing.assert_allclose(fc["q50"].to_numpy(), expected)


def test_naive_week_band_is_zero_on_exactly_weekly_series(weekly_periodic):
    fc = F.naive_week(weekly_periodic, 168)
    width = (fc["q95"] - fc["q05"]).max()
    assert width == pytest.approx(0, abs=1e-6)


def test_mean_4w_band_is_zero_on_exactly_weekly_series(weekly_periodic):
    # regressione: gli errori in campione devono usare il profilo allineato alla fase settimanale
    fc = F.mean_4w(weekly_periodic, 168)
    width = (fc["q95"] - fc["q05"]).max()
    assert width == pytest.approx(0, abs=1e-6)


# -------------------------------------------------------------- daily models

def assert_daily_after(fc: pd.DataFrame, last: pd.Timestamp, steps: int):
    assert len(fc) == steps
    assert fc.index.tz is None
    assert fc.index[0] == last + pd.Timedelta(days=1)
    assert (fc.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()


@pytest.mark.parametrize("model", [F.flat_28d, F.seasonal_ratio])
def test_daily_baselines(model, daily_prices):
    fc = model(daily_prices, 90)
    assert_daily_after(fc, daily_prices.index[-1], 90)
    assert_ordered_quantiles(fc)


def test_flat_28d_is_flat(daily_prices):
    fc = F.flat_28d(daily_prices, 30)
    assert np.allclose(fc["q50"], daily_prices.iloc[-28:].mean())
    assert (fc["q95"] > fc["q05"]).all()


def test_seasonal_ratio_follows_yearly_cycle(daily_prices):
    """With 4+ years of a strong yearly sine, the seasonal profile should track it."""
    fc = F.seasonal_ratio(daily_prices, 90)
    t = np.arange(len(daily_prices), len(daily_prices) + 90)
    truth = 100 + 25 * np.sin(2 * np.pi * t / 365.25)
    flat = np.full(90, daily_prices.iloc[-28:].mean())
    assert np.abs(fc["q50"] - truth).mean() < np.abs(flat - truth).mean()


@pytest.mark.parametrize("years", [0.5, 1.5, 2.5])
def test_seasonal_ratio_short_history(daily_prices, years):
    hist = daily_prices.iloc[: int(365 * years)]
    fc = F.seasonal_ratio(hist, 60)
    assert_daily_after(fc, hist.index[-1], 60)
    assert_ordered_quantiles(fc)
    # fewer than 3 years -> fixed +-25% band around the point forecast
    np.testing.assert_allclose(fc["q05"], fc["q50"] * 0.75)
    np.testing.assert_allclose(fc["q95"], fc["q50"] * 1.25)
    assert (fc["q50"] > 0).all()
