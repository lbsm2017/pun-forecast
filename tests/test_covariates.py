"""pun.covariates offline: HTTP finto, nessuna rete, nessun modello caricato."""

from __future__ import annotations

import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest
import requests

from pun import backtest as BT
from pun import covariates as C
from pun import forecast as F
from pun import sources as S

TZ = "Europe/Rome"


def utc_hours(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), freq="h")


def local_hours(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(start, tz=TZ).tz_convert("UTC"), periods=periods,
                         freq="h").tz_convert(TZ)


def const_weather(idx: pd.DatetimeIndex, value) -> pd.DataFrame:
    return pd.DataFrame({v: value for v in C.VARS}, index=idx, dtype="float64")


# ------------------------------------------------------------------ città

def test_zone_city_mapping():
    assert set(C.ZONE_CITY) == set(S.ZONE_WEIGHTS)
    assert len(set(C.ZONE_CITY.values())) == 7
    assert set(C.ZONE_CITY.values()) <= set(C.CITIES)
    assert C.ZONE_CITY["IT-North"] == "milano"
    assert C.ZONE_CITY["IT-Centre-North"] == "bologna"
    assert C.ZONE_CITY["IT-Centre-South"] == "roma"
    assert C.ZONE_CITY["IT-Sicily"] == "palermo"
    assert C.ZONE_CITY["IT-Sardinia"] == "cagliari"


def test_weighted_mean_renormalises_missing_values():
    idx = utc_hours("2026-01-01", "2026-01-01 02:00")
    a = const_weather(idx, 10.0)
    b = const_weather(idx, 20.0)
    b.iloc[1] = np.nan  # Bologna manca alla seconda ora
    out = C.weighted_mean({"milano": a, "bologna": b}, {"milano": 0.75, "bologna": 0.25})
    assert out["temperature_2m"].tolist() == pytest.approx([12.5, 10.0, 12.5])


def test_zone_weather_public_is_milano_only(monkeypatch):
    calls = []

    def fake(city, start, cache_dir, forecast, pause):
        calls.append(city)
        return const_weather(utc_hours("2026-01-01", "2026-01-01 03:00"), 5.0)

    monkeypatch.setattr(C, "city_weather", fake)
    out = C.zone_weather({"IT-North": 1.0}, cache_dir=None)
    assert calls == ["milano"]
    assert (out == 5.0).all().all()

    calls.clear()
    C.zone_weather(S.ZONE_WEIGHTS, cache_dir=None)
    assert sorted(calls) == sorted(C.CITIES)


# ------------------------------------------------------- HTTP con retry

class FakeResp:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body
        self.text = body if isinstance(body, str) else str(body)

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(C.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def fake_get(monkeypatch, responses):
    seq = list(responses)
    calls = []

    def get(url, params=None, timeout=None, headers=None):
        calls.append(params)
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(C.requests, "get", get)
    return calls


GOOD = {"hourly": {"time": ["2026-01-01T00:00"], "temperature_2m": [1.0],
                   "shortwave_radiation": [0.0], "wind_speed_100m": [3.0]}}


def test_get_json_retries_invalid_json_body_and_5xx(monkeypatch, no_sleep):
    calls = fake_get(monkeypatch, [
        FakeResp(200, "Unexpected error while streaming data: fileModifiedOrPrevalidationFailed"),
        FakeResp(503, "busy"),
        requests.ConnectionError("reset"),
        FakeResp(200, GOOD),
    ])
    assert C._get_json(C.ARCHIVE_URL, {}) == GOOD
    assert len(calls) == 4
    assert len(no_sleep) == 3 and no_sleep == sorted(no_sleep)  # backoff crescente


def test_get_json_gives_up_after_retries(monkeypatch, no_sleep):
    fake_get(monkeypatch, [FakeResp(200, "Unexpected error")] * 3)
    with pytest.raises(C.CovariateError, match="non JSON"):
        C._get_json(C.ARCHIVE_URL, {}, retries=3)


def test_get_json_does_not_retry_bad_request(monkeypatch, no_sleep):
    calls = fake_get(monkeypatch, [FakeResp(400, {"error": True, "reason": "out of range"})])
    with pytest.raises(C.CovariateError, match="400"):
        C._get_json(C.ARCHIVE_URL, {})
    assert len(calls) == 1 and not no_sleep


def test_city_history_caches_closed_years(monkeypatch, tmp_path, no_sleep):
    calls = []

    def fake(url, params):
        calls.append(params["start_date"])
        y = params["start_date"][:4]
        return {"hourly": {"time": [f"{y}-06-01T00:00", f"{y}-06-01T01:00"], "temperature_2m": [1.0, 2.0],
                           "shortwave_radiation": [0.0, 0.0], "wind_speed_100m": [3.0, None]}}

    monkeypatch.setattr(C, "_get_json", fake)
    start = date(date.today().year - 2, 1, 1)
    first = C.city_history("roma", start, tmp_path)
    n_first = len(calls)
    assert n_first == 3
    assert (tmp_path / "open-meteo" / "roma" / f"{start.year}.json").exists()
    second = C.city_history("roma", start, tmp_path)
    assert len(calls) - n_first < n_first  # gli anni chiusi vengono dalla cache
    pd.testing.assert_frame_equal(first, second)
    assert str(first.index.tz) == "UTC"
    assert first["wind_speed_100m"].isna().sum() == 3  # i null restano NaN


# ------------------------------------------------------------ climatologia

def test_climatology_shape_and_smoothing():
    idx = utc_hours("2024-01-01", "2025-12-31 23:00")
    wx = const_weather(idx, 0.0)
    wx.loc[wx.index.hour == 12] = 10.0
    clim = C.climatology(wx)
    assert len(clim) == 366 * 24
    assert not clim.isna().any().any()
    assert clim.loc[(100, 12), "temperature_2m"] == pytest.approx(10.0)
    assert clim.loc[(100, 3), "temperature_2m"] == pytest.approx(0.0)


def test_known_weather_uses_climatology_after_day_16(monkeypatch):
    monkeypatch.setattr(C, "standardize", lambda rows, n_ctx: rows)  # valori grezzi
    # osservato: 0 fino a fine novembre 2025, 10 da dicembre (anche "nel futuro")
    idx = utc_hours("2023-01-01", "2026-03-01")
    wx = const_weather(idx, 0.0)
    wx.loc[wx.index >= pd.Timestamp("2025-12-01", tz="UTC")] = 10.0
    cov = C.Covariates(weather=wx, weather_known_days=16)
    ctx = local_hours("2025-10-01", 24 * 92 + 1)  # +1: ora legale di ottobre; fine contesto 2025-12-31 23:00 → emissione 30/12 14:00
    assert ctx[-1] == pd.Timestamp("2025-12-31 23:00", tz=TZ)
    assert cov.issue_time(ctx) == pd.Timestamp("2025-12-30 14:00", tz=TZ)
    steps = 30 * 24
    arr = cov.known(ctx, steps)
    assert arr.shape == (len(C.VARS), len(ctx) + steps)
    fut = pd.date_range(ctx[-1].tz_convert("UTC") + pd.Timedelta(hours=1), periods=steps, freq="h")
    known_until = pd.Timestamp("2026-01-15 00:00", tz=TZ)  # giorno di emissione + 16
    early = fut < known_until
    h = arr[0, len(ctx):]
    assert early.sum() == 14 * 24  # 1-14 gennaio
    np.testing.assert_allclose(h[early], 10.0)       # "previsione" = osservato
    np.testing.assert_allclose(h[~early], 0.0)       # climatologia degli anni passati (gennaio = 0)
    np.testing.assert_allclose(arr[0, :len(ctx)], wx["temperature_2m"].reindex(ctx.tz_convert("UTC")))


def test_known_weather_build_mode_fills_after_forecast_end(monkeypatch):
    monkeypatch.setattr(C, "standardize", lambda rows, n_ctx: rows)
    # in produzione il frame finisce dove finisce la previsione Open-Meteo
    idx = utc_hours("2024-01-01", "2026-01-10 23:00")
    wx = const_weather(idx, 0.0)
    wx.loc[wx.index >= pd.Timestamp("2025-12-20", tz="UTC")] = 7.0
    ctx = local_hours("2025-11-01", 24 * 61)
    cov = C.Covariates(weather=wx, issue=pd.Timestamp("2025-12-30 14:00", tz=TZ))
    arr = cov.known(ctx, 20 * 24)
    fut = pd.date_range(ctx[-1].tz_convert("UTC") + pd.Timedelta(hours=1), periods=20 * 24, freq="h")
    h = arr[0, len(ctx):]
    in_fc = fut <= idx[-1]
    np.testing.assert_allclose(h[in_fc], 7.0)
    np.testing.assert_allclose(h[~in_fc], 0.0)


def test_standardize_uses_context_only():
    rows = np.array([[1.0, 2.0, 3.0, 100.0]])
    z = C.standardize(rows, 3)
    np.testing.assert_allclose(z[0, :3], [-1.2247449, 0.0, 1.2247449], rtol=1e-6)
    assert z[0, 3] == pytest.approx((100 - 2) / np.std([1, 2, 3]))
    flat = C.standardize(np.array([[5.0, 5.0, np.nan]]), 2)
    assert np.isfinite(flat).all()


# -------------------------------------------------------------------- gas

def test_gas_has_no_look_ahead():
    days = pd.date_range("2026-03-01", "2026-03-31", freq="D")
    daily = pd.Series(np.arange(len(days), dtype=float), index=days)  # valore = giorno - 1 marzo
    idx = local_hours("2026-03-05", 24 * 15)
    issue = pd.Timestamp("2026-03-12 14:00", tz=TZ)
    g = C.gas_hourly(daily, idx, issue)
    for t, v in zip(idx, g):
        known_day = min(t, issue).normalize() - pd.Timedelta(days=1)  # chiusura di ieri
        assert v == (known_day.tz_localize(None) - days[0]).days, t
    # dopo l'emissione resta l'ultima chiusura nota (11 marzo)
    assert set(g[idx > issue]) == {10.0}
    # cambiare i prezzi futuri non cambia nulla
    future = daily.copy()
    future[future.index >= "2026-03-12"] = 999.0
    np.testing.assert_array_equal(C.gas_hourly(future, idx, issue), g)


def test_gas_before_first_close_uses_first_known_value():
    daily = pd.Series([50.0, 51.0], index=pd.to_datetime(["2026-03-10", "2026-03-11"]))
    idx = local_hours("2026-03-09", 24 * 5)
    g = C.gas_hourly(daily, idx, pd.Timestamp("2026-03-13 14:00", tz=TZ))
    assert not np.isnan(g).any()
    assert g[0] == 50.0 and g[-1] == 51.0


def test_ttf_daily_without_yfinance(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "yfinance", None)  # import → ImportError
    assert C.ttf_daily(date(2025, 1, 1)) is None
    assert "yfinance" in capsys.readouterr().err


def test_past_covariate_shape():
    days = pd.date_range("2026-01-01", "2026-02-28", freq="D")
    cov = C.Covariates(gas=pd.Series(np.linspace(30, 40, len(days)), index=days))
    ctx = local_hours("2026-01-10", 24 * 30)
    p = cov.past(ctx)
    assert p.shape == (1, len(ctx))
    assert abs(p.mean()) < 1e-9


# ---------------------------------------------------- registro dei modelli

def test_split_name():
    assert F.split_name("timestral-28m") == ("timestral-28m", False, False)
    assert F.split_name("timestral-28m+meteo") == ("timestral-28m", True, False)
    assert F.split_name("timestral-209m+meteo+gas") == ("timestral-209m", True, True)
    assert F.split_name("timestral-28m+gas") == ("timestral-28m", False, True)


def test_hourly_models_only_with_available_covariates():
    assert F.hourly_models(None) == F.HOURLY
    wx = const_weather(utc_hours("2026-01-01", "2026-01-02"), 1.0)
    meteo = F.hourly_models(C.Covariates(weather=wx))
    assert {"timestral-28m+meteo", "timestral-209m+meteo"} <= set(meteo)
    assert not any("gas" in m for m in meteo)
    gas = F.hourly_models(C.Covariates(gas=pd.Series([1.0], index=pd.to_datetime(["2026-01-01"]))))
    assert "timestral-28m+gas" in gas and "timestral-28m+meteo" not in gas
    assert set(F.HOURLY) <= set(gas)


def test_run_hourly_with_registry(hourly_prices):
    registry = {"alias": F.naive_week}
    res = BT.run_hourly(hourly_prices, ["alias"], n_origins=2, registry=registry)
    ref = BT.run_hourly(hourly_prices, ["naive-week"], n_origins=2)
    assert res["alias"]["mae_7"] == ref["naive-week"]["mae_7"]


# ------------------------------------------------------------- gas in euro

def _days(*vals, start="2026-11-02"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="D"), dtype="float64")


def test_to_eur_lascia_invariato_il_prezzo_in_euro():
    p = _days(90.0, 91.0)
    assert C.to_eur(p, "EUR").tolist() == [90.0, 91.0]


def test_to_eur_converte_usd_col_cambio_del_giorno_o_precedente():
    p = _days(100.0, 110.0, 120.0)
    fx = _days(1.25, 1.10)                       # manca il terzo giorno: si usa l'ultimo cambio noto
    assert C.to_eur(p, "USD", fx).round(6).tolist() == [80.0, 100.0, round(120 / 1.10, 6)]


@pytest.mark.parametrize("currency", [None, "GBp"])
def test_to_eur_rifiuta_valute_ignote(currency):
    with pytest.raises(ValueError):
        C.to_eur(_days(1.0), currency)


def test_to_eur_usd_senza_cambio_e_un_errore():
    with pytest.raises(ValueError):
        C.to_eur(_days(1.0), "USD", None)
