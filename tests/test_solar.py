"""pun.solar: config, previsione FV (HTTP finto), simulazione batteria, decisioni (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pun import solar as SO

ROOT = Path(__file__).resolve().parent.parent
TZ = "Europe/Rome"
FORBIDDEN = ("conviene", "convenienza", "conveniente")

MINIMAL = """
[location]
lat = 45.0
lon = 9.0
[pv]
kwp = 6
[tariff]
fixed_price_eur_kwh = 0.30
"""


def _cfg(**kw) -> SO.SolarConfig:
    base = dict(lat=45.0, lon=9.0, kwp=6.0, fixed_price_eur_kwh=0.30,
                battery=SO.Battery(10.0, 5.0, 0.9, 0.1), base_load=[0.3] * 24,
                loads=[SO.Load("Bucato", 1.2, 2, (8, 22))])
    base.update(kw)
    return SO.SolarConfig(**base)


def _idx(start="2026-06-15 00:00", hours=96) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(start, tz=TZ), periods=hours, freq="h")


def _pv(day_peaks, flat=False, start="2026-06-15 00:00") -> pd.Series:
    """PV sintetico: per giorno una campana 6-20 con il picco dato (kWh/h), o un blocco 10-16."""
    idx = _idx(start, 24 * len(day_peaks))
    v = []
    for peak in day_peaks:
        for h in range(24):
            if flat:
                v.append(peak if 10 <= h < 16 else 0.0)
            else:
                v.append(peak * max(0.0, np.sin(np.pi * (h - 6) / 14)))
    return pd.Series(v, index=idx)


def _price(mwh=100.0, start="2026-06-15 00:00", hours=96) -> pd.Series:
    return pd.Series(mwh, index=_idx(start, hours)) / 1000  # €/kWh


def _run(cfg, pv, soc0, now, price_mwh=100.0):
    t0 = pd.Timestamp(now, tz=TZ)
    h = pv[pv.index >= t0]
    sim = SO.simulate(h, SO.base_series(cfg.base_load, h.index), cfg.battery, soc0)
    return SO.decide(cfg, sim, _price(price_mwh, hours=len(pv)), t0)[0]


# ------------------------------------------------------------------ config

def test_config_defaults(tmp_path):
    p = tmp_path / "impianto.toml"
    p.write_text(MINIMAL, encoding="utf-8")
    cfg = SO.load_config(p)
    assert (cfg.tilt_deg, cfg.azimuth_deg, cfg.performance_ratio) == (30, 0, 0.85)
    assert cfg.battery.capacity_kwh == 0 and cfg.battery.efficiency == 0.9 and cfg.battery.min_soc == 0.1
    assert cfg.ssp is True and cfg.cusf_eur_kwh == 0.02
    assert cfg.threshold_eur == 0.10 and cfg.max_wait_days == 3
    assert (cfg.margin_day12, cfg.margin_day3, cfg.initial_soc) == (1.5, 2.0, 0.5)
    assert cfg.base_load == SO.DEFAULT_BASE_LOAD and len(cfg.base_load) == 24
    assert cfg.loads == []


def test_example_config_parses():
    cfg = SO.load_config(ROOT / "impianto.example.toml")
    assert cfg.kwp == 6.0 and cfg.battery.capacity_kwh == 10.0 and cfg.ssp
    assert [ld.name for ld in cfg.loads] == ["Bucato", "Lavastoviglie"]
    assert cfg.loads[0].allowed_hours == (8, 22) and cfg.loads[0].duration_h == 2


def test_config_errors(tmp_path):
    p = tmp_path / "x.toml"
    p.write_text("[pv]\nkwp = 6\n", encoding="utf-8")
    with pytest.raises(ValueError, match="manca"):
        SO.load_config(p)
    p.write_text(MINIMAL + "[base_load]\nhourly_kw = [0.3, 0.3]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="24"):
        SO.load_config(p)


# ------------------------------------------------------------ previsione FV

class _Resp:
    def __init__(self, status, payload=None, bad_json=False):
        self.status_code, self._payload, self._bad = status, payload, bad_json

    def json(self):
        if self._bad:
            raise ValueError("invalid json")
        return self._payload


def _om_payload():
    t0 = int(pd.Timestamp("2026-06-15 00:00", tz=TZ).timestamp())
    times = [t0 + 3600 * k for k in range(48)]
    gti = [0.0] * 48
    gti[13] = 800.0  # media 12:00-13:00
    return {"hourly": {"time": times, "global_tilted_irradiance": gti, "cloud_cover": [10] * 48}}


def test_fetch_pv_conversion_retry_and_cache(monkeypatch, tmp_path):
    calls = []
    replies = [_Resp(503), _Resp(200, bad_json=True), _Resp(200, _om_payload())]

    def fake_get(url, params=None, **kw):
        calls.append(params)
        return replies.pop(0)

    monkeypatch.setattr(SO.requests, "get", fake_get)
    monkeypatch.setattr(SO.time, "sleep", lambda s: None)
    cfg = _cfg(kwp=6.0, performance_ratio=0.85, tilt_deg=35, azimuth_deg=-20)
    df = SO.fetch_pv_forecast(cfg, days=3, cache_dir=tmp_path)
    assert len(calls) == 3
    p = calls[0]
    assert p["hourly"] == "global_tilted_irradiance,cloud_cover"
    assert (p["tilt"], p["azimuth"], p["forecast_days"], p["timezone"]) == (35, -20, 4, TZ)
    # 800 W/m² nell'ora che termina alle 13 → riferita all'ora 12:00-13:00
    noon = pd.Timestamp("2026-06-15 12:00", tz=TZ)
    assert df.loc[noon, "pv_kwh"] == pytest.approx(6.0 * 800 / 1000 * 0.85)
    assert df["pv_kwh"].sum() == pytest.approx(4.08)
    assert str(df.index.tz) == TZ
    # seconda chiamata: dalla cache, niente rete; nessuna coordinata nel nome del file
    df2 = SO.fetch_pv_forecast(cfg, days=3, cache_dir=tmp_path)
    assert len(calls) == 3 and df2["pv_kwh"].sum() == pytest.approx(4.08)
    assert all("45" not in f.name for f in tmp_path.iterdir())


def test_fetch_pv_gives_up_on_client_error(monkeypatch):
    monkeypatch.setattr(SO.requests, "get", lambda *a, **k: _Resp(400))
    monkeypatch.setattr(SO.time, "sleep", lambda s: None)
    with pytest.raises(SO.SolarError, match="400"):
        SO.fetch_pv_forecast(_cfg())


# ---------------------------------------------------------- simulazione

@pytest.mark.parametrize("soc0", [0.0, 0.1, 0.5, 1.0])
def test_simulation_invariants(soc0):
    rng = np.random.default_rng(1)
    pv = _pv([5, 1, 6, 0.5]) + rng.uniform(0, 0.3, 96)
    bat = SO.Battery(10.0, 3.0, 0.9, 0.1)
    base = SO.base_series(SO.DEFAULT_BASE_LOAD, pv.index)
    extra = rng.uniform(0, 1.0, 96)
    s = SO.simulate(pv, base, bat, soc0, extra)
    assert (s["soc"] <= 10.0 + 1e-9).all() and (s["soc"] >= 0).all()
    if soc0 >= 0.1:
        assert (s["soc"] >= 1.0 - 1e-9).all()  # mai sotto min_soc se si parte sopra
    assert (s[["charge", "discharge", "grid", "export"]] >= -1e-12).all().all()
    assert (s["charge"] <= 3.0 + 1e-9).all() and (s["discharge"] <= 3.0 + 1e-9).all()
    assert not ((s["charge"] > 0) & (s["discharge"] > 0)).any()
    lhs = s["pv"] + s["discharge"] + s["grid"]
    rhs = s["base"] + s["extra"] + s["charge"] + s["export"]
    assert np.allclose(lhs, rhs)
    # soc coerente con carica (× rendimento) e scarica
    prev = np.concatenate([[soc0 * 10.0], s["soc"].to_numpy()[:-1]])
    assert np.allclose(s["soc"], prev + 0.9 * s["charge"] - s["discharge"])
    assert SO._soc0(s, bat) == pytest.approx(soc0)


def test_simulation_without_battery():
    pv = _pv([4])
    s = SO.simulate(pv, [0.3] * 24, SO.Battery(), 0.5)
    assert (s["soc"] == 0).all() and (s["charge"] == 0).all()
    assert np.allclose(s["export"] - s["grid"], s["pv"] - s["base"])


# ------------------------------------------------------------- decisioni

def _check_text(d):
    assert d["text"].startswith("Bucato:")
    assert not any(w in d["text"].lower() for w in FORBIDDEN)
    assert d["verdict"] in SO.VERDICTS


def test_sunny_tomorrow_waits_for_sun():
    d = _run(_cfg(), _pv([0, 6, 6, 6]), soc0=0.1, now="2026-06-15 19:00")
    _check_text(d)
    assert d["verdict"] == "aspetta_il_sole"
    assert d["day"] == "domani" and 8 <= d["window"][0] and d["window"][1] <= 22
    assert d["cost_now"] == pytest.approx(0.36, abs=0.01)  # 1,2 kWh × 0,30 dalla rete
    assert d["cost_best"] < 0.2 and d["saving"] >= 0.1
    assert "domani" in d["text"] and "col sole" in d["text"]


def test_cloudy_days_use_grid():
    d = _run(_cfg(), _pv([0, 0.4, 0.3, 0.4]), soc0=0.1, now="2026-06-15 19:00")
    _check_text(d)
    assert d["verdict"] == "adesso_rete"
    assert d["cost_best"] is None and d["cost_now"] == pytest.approx(0.36, abs=0.01)


def test_full_battery_and_sunny_tomorrow_uses_battery():
    d = _run(_cfg(), _pv([0, 6, 6, 6]), soc0=1.0, now="2026-06-15 19:00")
    _check_text(d)
    assert d["verdict"] == "adesso_batteria"
    assert d["start"].startswith("2026-06-15T19:00")
    # costo ≈ immissione persa domani per ricaricare: 1,2 / 0,9 × (0,10 + 0,02)
    assert d["cost_now"] == pytest.approx(1.2 / 0.9 * 0.12, abs=0.01)


def test_full_battery_and_cloudy_days_is_not_free():
    d = _run(_cfg(), _pv([0, 0.3, 0.3, 0.3]), soc0=1.0, now="2026-06-15 19:00")
    # senza sole la batteria si svuota comunque nei giorni dopo: usarla ora anticipa
    # solo il prelievo dalla rete, quindi il carico costa come dalla rete
    assert d["verdict"] == "adesso_rete"
    assert d["cost_now"] == pytest.approx(1.2 * 0.30, abs=0.01)


def test_ssp_export_close_to_fixed_price_means_no_difference():
    # prezzo orario 280 €/MWh + CUSf 0,02 = 0,30 €/kWh = prezzo fisso
    d = _run(_cfg(), _pv([0, 6, 6, 6]), soc0=0.1, now="2026-06-15 19:00", price_mwh=280)
    _check_text(d)
    assert d["verdict"] == "nessuna_differenza"
    assert d["saving"] < 0.1
    assert "nessuna differenza" in d["text"] and "0,10 €" in d["text"]


def test_sun_now():
    d = _run(_cfg(), _pv([6, 0, 0, 0]), soc0=1.0, now="2026-06-15 11:00")
    _check_text(d)
    assert d["verdict"] == "adesso_sole" and d["start"].startswith("2026-06-15T11:00")


def test_day3_margin_is_stricter():
    # niente batteria; blocco piatto 10-16 da 1,35 kWh/h: surplus in 2 ore = 2,1 kWh
    # = 1,75 × 1,2 kWh → basta per i giorni 1-2 (1,5×) ma non per il giorno 3 (2×)
    cfg = _cfg(battery=SO.Battery())
    d1 = _run(cfg, _pv([0, 1.35, 0, 0], flat=True), soc0=0, now="2026-06-15 19:00")
    d3 = _run(cfg, _pv([0, 0, 0, 1.35], flat=True), soc0=0, now="2026-06-15 19:00")
    assert d1["verdict"] == "aspetta_il_sole" and d1["surplus_kwh"] == pytest.approx(2.1)
    assert d3["verdict"] == "adesso_rete"
    # con un surplus più ampio anche il giorno 3 basta
    d3b = _run(cfg, _pv([0, 0, 0, 1.6], flat=True), soc0=0, now="2026-06-15 19:00")
    assert d3b["verdict"] == "aspetta_il_sole" and "più incerta" in d3b["confidence"]


def test_allowed_hours_respected_and_night_now():
    # alle 23 le ore ammesse 8-22 sono chiuse: "adesso" diventa domani alle 8
    d = _run(_cfg(), _pv([0, 0.3, 0.3, 0.3]), soc0=0.1, now="2026-06-15 23:00")
    assert d["start"].startswith("2026-06-16T08:00")
    assert "domani" in d["text"] or d["verdict"] == "adesso_rete"


# ------------------------------------------------------------ blocco JSON

def test_solar_block_json_shape():
    cfg = _cfg(loads=[SO.Load("Bucato", 1.2, 2, (8, 22)), SO.Load("Lavastoviglie", 1.0, 2, (8, 23))])
    pv = pd.DataFrame({"pv_kwh": _pv([5, 6, 6, 6]), "cloud_cover": 10.0})
    prices = pd.DataFrame({"q05": 80.0, "q50": 100.0, "q95": 130.0}, index=_idx())
    blk = SO.solar_block(cfg, prices, pd.Timestamp("2026-06-15 19:30", tz=TZ), pv=pv)
    json.dumps(blk)  # serializzabile
    assert [d["label"] for d in blk["days"]] == ["oggi", "domani", "dopodomani", "giovedì"]
    assert set(blk["days"][1]) == {"date", "label", "pv_kwh", "surplus_kwh",
                                   "battery_full_hours", "battery_full"}
    assert blk["days"][1]["battery_full_hours"] > 0
    assert [ld["name"] for ld in blk["loads"]] == ["Bucato", "Lavastoviglie"]
    for ld in blk["loads"]:
        assert ld["cost_now"] == round(ld["cost_now"], 3)
        assert not any(w in ld["text"].lower() for w in FORBIDDEN)
    assert blk["fixed_price"] == 0.3 and "Open-Meteo" in blk["attribution"]
