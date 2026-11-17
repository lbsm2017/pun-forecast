"""pun.build.build end to end, offline: prezzi sintetici, baseline al posto di Timestral,
previsione FV finta. Copre "Rete o sole?" nel flusso locale e il ritorno al modello base."""

from __future__ import annotations

import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pun import build as B
from pun import forecast as F
from pun import solar as SO

ROOT = Path(__file__).resolve().parent.parent
TZ = "Europe/Rome"


def _prices(days_back: int = 400) -> pd.Series:
    """Prezzi orari €/MWh fino a fine domani (come dopo l'asta del giorno prima)."""
    start = pd.Timestamp(date.today() - timedelta(days=days_back), tz=TZ)
    end = pd.Timestamp(date.today() + timedelta(days=2), tz=TZ)
    idx = pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h",
                        inclusive="left").tz_convert(TZ)
    t = np.arange(len(idx))
    rng = np.random.default_rng(1)
    v = 110 + 25 * np.sin(2 * np.pi * t / 24) + 8 * np.sin(2 * np.pi * t / 168) + rng.normal(0, 2, len(idx))
    return pd.Series(v, index=idx)


def _metrics(mae: float) -> dict:
    return {"mae_1": mae, "mae_7": mae + 2, "mae_30": mae + 6, "daily_mae_30": mae + 4,
            "coverage90": 0.85, "hit6": 0.7, "n": 26, "seconds": 1.0}


def _bt_dict(hourly_model: str) -> dict:
    return {
        "as_of": date.today().isoformat(),
        "hourly": {"naive-week": _metrics(18.0), "timestral-28m": _metrics(13.0),
                   "timestral-28m+meteo": _metrics(12.0)},
        "daily": {"flat-28d": {"mae_30": 19.0, "mae_90": 25.0, "coverage90": 0.73,
                               "month1_mae": 15.0, "month2_mae": 20.0, "month3_mae": 25.0}},
        "hourly_model": hourly_model,
        "daily_model": "flat-28d",
    }


def _backtest(path: Path, hourly_model: str) -> Path:
    path.write_text(json.dumps(_bt_dict(hourly_model)), encoding="utf-8")
    return path


def _fake_pv(cfg, days=3, cache_dir=None):
    idx = pd.date_range(pd.Timestamp(date.today(), tz=TZ), periods=24 * (days + 1), freq="h")
    pv = [cfg.kwp * 0.7 * max(0.0, np.sin(np.pi * (t.hour - 7) / 10)) for t in idx]
    return pd.DataFrame({"pv_kwh": pv, "cloud_cover": 20.0}, index=idx)


@pytest.fixture
def offline(monkeypatch):
    """Nessuna rete: prezzi sintetici, niente covariate, Timestral sostituito da una baseline."""
    s = _prices()
    monkeypatch.setattr(B, "load_prices", lambda p, cache, start, progress=None: (s, p.label))
    monkeypatch.setattr(B, "load_weather", lambda *a, **k: None)
    monkeypatch.setattr(B, "load_gas", lambda *a, **k: None)
    monkeypatch.setitem(F.HOURLY, "timestral-28m", F.naive_week)
    monkeypatch.setattr(SO, "fetch_pv_forecast", _fake_pv)
    return s


def _local(tmp_path: Path, impianto: bool = True) -> B.Profile:
    if impianto:
        shutil.copy(ROOT / "impianto.example.toml", tmp_path / "impianto.toml")
    return B.profile("local", tmp_path)


def test_local_build_adds_solar_block(offline, tmp_path):
    p = _local(tmp_path)
    data = B.build(p, tmp_path / "cache", _backtest(tmp_path / "bt.json", "naive-week"))
    sol = data["solar"]
    json.dumps(data)
    assert [d["label"] for d in sol["days"]][:2] == ["oggi", "domani"]
    assert [ld["name"] for ld in sol["loads"]] == ["Bucato", "Lavastoviglie"]
    assert all(ld["verdict"] in SO.VERDICTS for ld in sol["loads"])
    assert SO.ATTRIBUTION in data["attribution"]
    assert data["attribution"][-1].startswith("Previsione: Timestral")


def test_public_build_never_has_solar(offline, tmp_path, monkeypatch):
    shutil.copy(ROOT / "impianto.example.toml", tmp_path / "impianto.toml")
    monkeypatch.setattr(SO, "solar_block", lambda *a, **k: pytest.fail("solar nel profilo pubblico"))
    p = B.profile("public", tmp_path, out=tmp_path / "site")
    data = B.build(p, tmp_path / "cache", _backtest(tmp_path / "bt.json", "naive-week"))
    assert "solar" not in data
    assert not any("fotovoltaica" in a for a in data["attribution"])


def test_local_without_config_has_no_solar(offline, tmp_path):
    data = B.build(_local(tmp_path, impianto=False), tmp_path / "cache",
                   _backtest(tmp_path / "bt.json", "naive-week"))
    assert "solar" not in data


def test_solar_errors_are_warnings(offline, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise SO.SolarError("Open-Meteo: HTTP 503")
    monkeypatch.setattr(SO, "fetch_pv_forecast", boom)
    data = B.build(_local(tmp_path), tmp_path / "cache", _backtest(tmp_path / "bt.json", "naive-week"))
    assert "solar" not in data and SO.ATTRIBUTION not in data["attribution"]
    assert "fotovoltaico non disponibile" in capsys.readouterr().err

    (tmp_path / "impianto.toml").write_text("[location]\nlat = 45.0\n", encoding="utf-8")  # manca [pv]
    data = B.build(B.profile("local", tmp_path), tmp_path / "cache", tmp_path / "bt.json")
    assert "solar" not in data
    assert "impianto.toml" in capsys.readouterr().err


def test_solar_price_series_joins_actual_and_forecast(offline):
    today = date.today()
    fc = F.naive_week(offline, 72)
    out = B.solar_price_series(offline, fc, today)
    assert out.index.is_monotonic_increasing and not out.index.duplicated().any()
    assert out.index[0] == offline[offline.index.date >= today].index[0]
    last_real = offline.index[-1]
    assert (out[out.index <= last_real] == offline[offline.index.date >= today]).all()
    assert (out[out.index > last_real] == fc["q50"]).all()


def test_gme_label_mixed_unless_gme_covers_the_shown_period():
    all_idx = pd.date_range("2026-01-01", "2026-11-18 23:00", freq="h", tz=TZ)
    recent = all_idx[all_idx >= pd.Timestamp("2026-11-03", tz=TZ)]
    assert B.gme_label(recent, all_idx) == "PUN ufficiale GME + stima 7 zone"
    assert B.gme_label(recent[:-24], all_idx) == "PUN ufficiale GME + stima 7 zone"
    long = all_idx[all_idx >= pd.Timestamp("2026-07-01", tz=TZ)]
    assert B.gme_label(long, all_idx) == "PUN ufficiale GME"


# ------------------------------------------------------------ ritorno al modello base

def test_reliability_reports_model_actually_used():
    bt = _bt_dict("timestral-28m+meteo")
    r = B.reliability(bt, "timestral-28m")
    assert r["model"] == "timestral-28m" and r["figures_of"] == "timestral-28m"
    assert r["picked"] == "timestral-28m+meteo"
    assert r["mae_1"] == B.kwh(13.0)
    # modello usato assente dal backtest: cifre del modello scelto, dichiarato
    r = B.reliability(bt, "timestral-209m")
    assert r["model"] == "timestral-209m" and r["figures_of"] == "timestral-28m+meteo"
    # senza fallback: tutto coincide
    r = B.reliability(bt)
    assert r["model"] == r["figures_of"] == r["picked"] == "timestral-28m+meteo"


def test_build_falls_back_without_covariates(offline, tmp_path, capsys):
    p = B.profile("public", tmp_path, out=tmp_path / "site")
    data = B.build(p, tmp_path / "cache", _backtest(tmp_path / "bt.json", "timestral-28m+meteo"))
    assert data["model"]["hourly"] == "timestral-28m"
    r = data["reliability"]
    assert r["model"] == "timestral-28m" and r["picked"] == "timestral-28m+meteo"
    assert r["mae_1"] == B.kwh(13.0)  # cifre del modello usato, non di quello con meteo (12,0)
    assert not any("Open-Meteo.com" in a for a in data["attribution"])
    assert "uso timestral-28m" in capsys.readouterr().err
