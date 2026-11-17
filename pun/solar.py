"""Rete o sole? Produzione fotovoltaica prevista, batteria e momento giusto per i carichi flessibili.

Solo flusso locale. La configurazione personale sta in `data/impianto.toml` (git-ignored,
mai pubblicata); `impianto.example.toml` nella radice del repo è un esempio commentato.
Produzione prevista da Open-Meteo (CC BY 4.0, uso non commerciale).

Come si valuta un kWh (contratto a prezzo fisso + scambio sul posto):
- dalla rete: prezzo fisso tutto incluso;
- immesso: prezzo orario previsto + CUSf (al massimo il prezzo fisso), 0 se negativo;
- in batteria: non ha un prezzo fisso. Ogni ipotesi ("carico che parte all'ora t") viene
  ri-simulata ora per ora sull'intero orizzonte: se il sole dei giorni dopo ricarica comunque
  la batteria, usarla costa solo l'immissione persa; altrimenti costa rete evitata più tardi.
  L'energia rimasta in batteria a fine orizzonte vale prezzo fisso × rendimento.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import tomllib
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

TZ = "Europe/Rome"
OM_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "pun-forecast/0.1"
CACHE_MAX_AGE_S = 3600  # la previsione cambia nel corso del giorno: cache di un'ora
ATTRIBUTION = "Previsione fotovoltaica: Open-Meteo (CC BY 4.0)"

# Consumo di base di una famiglia tipo, kW medi per ora 0..23 (~7,7 kWh al giorno)
DEFAULT_BASE_LOAD = [0.20, 0.18, 0.17, 0.17, 0.17, 0.20, 0.30, 0.45, 0.40, 0.30, 0.28, 0.30,
                     0.40, 0.35, 0.28, 0.26, 0.28, 0.35, 0.50, 0.60, 0.55, 0.45, 0.35, 0.25]
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
VERDICTS = ("aspetta_il_sole", "adesso_sole", "adesso_batteria", "nessuna_differenza", "adesso_rete")


class SolarError(RuntimeError):
    pass


# ------------------------------------------------------------------ config

@dataclass
class Battery:
    capacity_kwh: float = 0.0
    power_kw: float = 0.0
    efficiency: float = 0.9   # andata e ritorno, applicato in carica
    min_soc: float = 0.1      # frazione della capacità sotto cui non si scarica


@dataclass
class Load:
    name: str
    kwh: float
    duration_h: int
    allowed_hours: tuple[int, int] = (0, 24)  # [inizio, fine); se inizio > fine scavalca la mezzanotte


@dataclass
class SolarConfig:
    lat: float
    lon: float
    kwp: float
    fixed_price_eur_kwh: float
    tilt_deg: float = 30.0
    azimuth_deg: float = 0.0  # convenzione Open-Meteo: 0 sud, -90 est, 90 ovest
    performance_ratio: float = 0.85
    battery: Battery = field(default_factory=Battery)
    ssp: bool = True
    cusf_eur_kwh: float = 0.02
    base_load: list[float] = field(default_factory=lambda: list(DEFAULT_BASE_LOAD))
    loads: list[Load] = field(default_factory=list)
    threshold_eur: float = 0.10
    max_wait_days: int = 3
    margin_day12: float = 1.5
    margin_day3: float = 2.0
    initial_soc: float = 0.5


def parse_config(d: dict) -> SolarConfig:
    try:
        loc, pv, tar = d["location"], d["pv"], d["tariff"]
        bat, dec = d.get("battery", {}), d.get("decision", {})
        cfg = SolarConfig(
            lat=float(loc["lat"]), lon=float(loc["lon"]), kwp=float(pv["kwp"]),
            fixed_price_eur_kwh=float(tar["fixed_price_eur_kwh"]),
            tilt_deg=float(pv.get("tilt_deg", 30)), azimuth_deg=float(pv.get("azimuth_deg", 0)),
            performance_ratio=float(pv.get("performance_ratio", 0.85)),
            battery=Battery(float(bat.get("capacity_kwh", 0)), float(bat.get("power_kw", 0)),
                            float(bat.get("efficiency", 0.9)), float(bat.get("min_soc", 0.1))),
            ssp=bool(tar.get("ssp", True)), cusf_eur_kwh=float(tar.get("cusf_eur_kwh", 0.02)),
            base_load=[float(x) for x in d.get("base_load", {}).get("hourly_kw", DEFAULT_BASE_LOAD)],
            loads=[Load(str(x["name"]), float(x["kwh"]), int(math.ceil(float(x.get("duration_h", 1)))),
                        tuple(int(h) for h in x.get("allowed_hours", (0, 24))))
                   for x in d.get("loads", [])],
            threshold_eur=float(dec.get("threshold_eur", 0.10)),
            max_wait_days=int(dec.get("max_wait_days", 3)),
            margin_day12=float(dec.get("margin_day12", 1.5)),
            margin_day3=float(dec.get("margin_day3", 2.0)),
            initial_soc=float(d.get("initial_soc", bat.get("initial_soc", 0.5))),
        )
    except KeyError as e:
        raise ValueError(f"impianto.toml: manca la voce {e}") from None
    if len(cfg.base_load) != 24:
        raise ValueError("impianto.toml: base_load.hourly_kw deve avere 24 valori (ore 0-23)")
    for ld in cfg.loads:
        ok_win = len(ld.allowed_hours) == 2 and all(0 <= h <= 24 for h in ld.allowed_hours)
        if not ok_win or ld.kwh <= 0 or ld.duration_h < 1:
            raise ValueError(f"impianto.toml: carico '{ld.name}' non valido")
    if not 0 <= cfg.battery.min_soc < 1 or not 0 < cfg.battery.efficiency <= 1:
        raise ValueError("impianto.toml: batteria non valida (min_soc in [0,1), efficiency in (0,1])")
    return cfg


def load_config(path: str | Path) -> SolarConfig:
    with open(path, "rb") as f:
        return parse_config(tomllib.load(f))


# ------------------------------------------------------- previsione FV

def _om_request(params: dict, retries: int = 4) -> dict:
    wait, err = 2.0, ""
    for _ in range(retries):
        try:
            r = requests.get(OM_URL, params=params, timeout=30, headers={"User-Agent": USER_AGENT})
            if r.status_code == 200:
                data = r.json()
                if "hourly" in data:
                    return data
                err = "risposta senza 'hourly'"
            else:
                err = f"HTTP {r.status_code}"
                if r.status_code != 429 and r.status_code < 500:
                    break
        except (requests.RequestException, ValueError) as e:  # rete instabile o JSON non valido
            err = str(e)
        time.sleep(wait)
        wait = min(wait * 2, 60)
    raise SolarError(f"Open-Meteo: {err}")


def pv_from_openmeteo(data: dict, cfg: SolarConfig) -> pd.DataFrame:
    """Risposta Open-Meteo → DataFrame orario (inizio ora, Europe/Rome): pv_kwh, cloud_cover."""
    h = data["hourly"]
    idx = pd.to_datetime(h["time"], unit="s", utc=True).tz_convert(TZ)
    # la radiazione Open-Meteo è la media dell'ora *precedente*: la riporto all'inizio dell'ora
    idx = idx - pd.Timedelta(hours=1)
    gti = pd.Series(h["global_tilted_irradiance"], index=idx, dtype=float).fillna(0).clip(lower=0)
    cloud = pd.Series(h.get("cloud_cover", [np.nan] * len(idx)), index=idx, dtype=float)
    return pd.DataFrame({"pv_kwh": cfg.kwp * gti / 1000 * cfg.performance_ratio, "cloud_cover": cloud})


def fetch_pv_forecast(cfg: SolarConfig, days: int = 3, cache_dir: Path | None = None) -> pd.DataFrame:
    """Produzione FV oraria prevista (kWh) da oggi a oggi + `days`."""
    params = {"latitude": cfg.lat, "longitude": cfg.lon,
              "hourly": "global_tilted_irradiance,cloud_cover",
              "tilt": cfg.tilt_deg, "azimuth": cfg.azimuth_deg,
              "forecast_days": days + 1, "timezone": TZ, "timeformat": "unixtime"}
    cache = None
    if cache_dir is not None:
        key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:12]
        cache = Path(cache_dir) / f"openmeteo_pv_{key}.json"  # niente coordinate nel nome
        if cache.exists() and time.time() - cache.stat().st_mtime < CACHE_MAX_AGE_S:
            return pv_from_openmeteo(json.loads(cache.read_text(encoding="utf-8")), cfg)
    data = _om_request(params)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    return pv_from_openmeteo(data, cfg)


# --------------------------------------------------------- simulazione

def base_series(base_load: list[float], index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series([base_load[t.hour] for t in index], index=index, dtype=float)


def simulate(pv_kwh: pd.Series, base_kw, battery: Battery, soc0: float,
             extra: np.ndarray | None = None) -> pd.DataFrame:
    """Bilancio ora per ora. Il surplus carica la batteria (limiti di potenza e capacità), il resto
    è immesso; il deficit scarica la batteria fino a min_soc, il resto viene dalla rete.
    soc0 è una frazione della capacità; la colonna soc è in kWh a fine ora.
    Bilancio: pv + discharge + grid = base + extra + charge + export."""
    idx = pv_kwh.index
    pv = np.clip(pv_kwh.to_numpy(float), 0, None)
    base = (base_kw.reindex(idx).to_numpy(float) if isinstance(base_kw, pd.Series)
            else base_series(list(base_kw), idx).to_numpy())
    ext = np.zeros(len(idx)) if extra is None else np.asarray(extra, float)
    cap, p, eff = battery.capacity_kwh, battery.power_kw, battery.efficiency
    lo = battery.min_soc * cap
    soc = float(np.clip(soc0 * cap, 0, cap))
    cols = {k: np.zeros(len(idx)) for k in ("charge", "discharge", "soc", "grid", "export")}
    for i in range(len(idx)):
        net = pv[i] - base[i] - ext[i]
        if net >= 0:
            ch = min(net, p, max(cap - soc, 0) / eff)
            soc += ch * eff
            cols["charge"][i], cols["export"][i] = ch, net - ch
        else:
            dis = min(-net, p, max(soc - lo, 0))
            soc -= dis
            cols["discharge"][i], cols["grid"][i] = dis, -net - dis
        cols["soc"][i] = soc
    return pd.DataFrame({"pv": pv, "base": base, "extra": ext, **cols}, index=idx)


def _soc0(sim: pd.DataFrame, battery: Battery) -> float:
    """Stato di carica (frazione) all'inizio della simulazione."""
    if battery.capacity_kwh <= 0:
        return 0.0
    r = sim.iloc[0]
    return (r.soc - r.charge * battery.efficiency + r.discharge) / battery.capacity_kwh


# ------------------------------------------------------------ valori

def _ts(now) -> pd.Timestamp:
    t = pd.Timestamp(now)
    return t.tz_localize(TZ) if t.tzinfo is None else t.tz_convert(TZ)


def _align(price: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """Prezzi orari sull'indice della simulazione; buchi riempiti con la media della stessa ora."""
    p = price[~price.index.duplicated()].sort_index()
    if p.empty:
        raise ValueError("nessun prezzo orario disponibile")
    a = p.reindex(idx)
    if a.isna().all():
        a = pd.Series(float(p.iloc[-168:].mean()), index=idx)
    return a.fillna(a.groupby(a.index.hour).transform("mean")).ffill().bfill()


def export_value(price_kwh: pd.Series, cfg: SolarConfig) -> pd.Series:
    """Valore di un kWh immesso: con scambio sul posto prezzo orario + CUSf, al massimo il prezzo fisso."""
    if cfg.ssp:
        return (price_kwh + cfg.cusf_eur_kwh).clip(lower=0, upper=cfg.fixed_price_eur_kwh)
    return price_kwh.clip(lower=0)


def _cost(sim: pd.DataFrame, exp_val: pd.Series, cfg: SolarConfig) -> float:
    b = cfg.battery
    left = max(sim["soc"].iloc[-1] - b.min_soc * b.capacity_kwh, 0)
    return float((sim["grid"] * cfg.fixed_price_eur_kwh).sum() - (sim["export"] * exp_val).sum()
                 - left * cfg.fixed_price_eur_kwh * b.efficiency)


# ------------------------------------------------------------ decisione

def _allowed(h: int, win: tuple[int, int]) -> bool:
    a, b = win
    return a <= h < b if a < b else (h >= a or h < b) if a > b else True


def _eur(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _num(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _day_label(d: date, today: date) -> str:
    return {0: "oggi", 1: "domani", 2: "dopodomani"}.get((d - today).days, WEEKDAYS[d.weekday()])


def _window(start: pd.Timestamp, n: int) -> list[int]:
    end = (start + pd.Timedelta(hours=n)).hour
    return [start.hour, end if end > start.hour else end + 24]


def _decide_load(cfg, load, sim, exp_val, base_cost, soc0, now) -> dict:
    idx, n = sim.index, load.duration_h
    per, E = load.kwh / n, load.kwh
    surplus = (sim["pv"] - sim["base"]).clip(lower=0).to_numpy()
    t0, last_day = now.floor("h"), now.date() + timedelta(days=cfg.max_wait_days)
    cands = []
    for i, t in enumerate(idx):
        if i + n > len(idx) or t.date() > last_day:
            break
        if t < t0 or not all(_allowed(h.hour, load.allowed_hours) for h in idx[i:i + n]):
            continue
        extra = np.zeros(len(idx))
        extra[i:i + n] = per
        s = simulate(sim["pv"], sim["base"], cfg.battery, soc0, extra)
        off = (t.date() - now.date()).days
        cands.append({
            "start": t, "cost": _cost(s, exp_val, cfg) - base_cost, "offset": off,
            "surplus": float(surplus[i:i + n].sum()),
            "battery": float((s["discharge"] - sim["discharge"]).iloc[i:i + n].sum()) / E,
            "margin": cfg.margin_day3 if off >= 3 else cfg.margin_day12,
        })
    name = load.name
    if not cands:
        return {"name": name, "kwh": E, "verdict": None,
                "text": f"{name}: nessuna fascia oraria ammessa nei giorni previsti."}

    grid_full = E * cfg.fixed_price_eur_kwh
    sunny = [c for c in cands if c["surplus"] >= c["margin"] * E]
    now_c = cands[0]
    best = None
    if sunny:  # a parità di costo (±1 cent) la finestra con più surplus: più margine contro le nuvole
        low = min(c["cost"] for c in sunny)
        best = max((c for c in sunny if c["cost"] <= low + 0.01), key=lambda c: c["surplus"])
    diff = now_c["cost"] - best["cost"] if best else 0.0
    thr = cfg.threshold_eur
    today = now.date()
    is_now = now_c["start"] <= t0
    when_now = "adesso" if is_now else (f"{_day_label(now_c['start'].date(), today)} "
                                        f"dalle {now_c['start'].hour}")
    chosen, note = now_c, ""

    def sun_note(c):
        r = c["surplus"] / E
        txt = f"surplus previsto {_num(c['surplus'])} kWh ({_num(r)}× il carico): sole " + (
            "probabile" if r >= 2 * c["margin"] else "possibile")
        return txt + ("; previsione a più giorni, più incerta" if c["offset"] >= 2 else "")

    if best and best["start"] > now_c["start"] and diff >= thr:
        verdict, chosen, note = "aspetta_il_sole", best, sun_note(best)
        h0, h1 = _window(best["start"], n)
        text = (f"{name}: {_day_label(best['start'].date(), today)} {h0}–{h1} col sole, "
                f"~{_eur(best['cost'])} € invece di ~{_eur(now_c['cost'])} € {when_now}.")
    elif now_c["surplus"] >= now_c["margin"] * E and grid_full - now_c["cost"] >= thr:
        verdict, note = "adesso_sole", sun_note(now_c)
        text = (f"{name}: {when_now} c'è sole a sufficienza, ~{_eur(now_c['cost'])} € "
                f"invece di ~{_eur(grid_full)} € dalla rete.")
    elif now_c["battery"] >= 0.8 and grid_full - now_c["cost"] >= thr:
        verdict, note = "adesso_batteria", "il sole previsto ricarica comunque la batteria"
        text = (f"{name}: {when_now} con la batteria, ~{_eur(now_c['cost'])} €: il sole previsto "
                f"la ricarica comunque (dalla rete ~{_eur(grid_full)} €).")
    elif best:
        verdict = "nessuna_differenza"
        note = f"differenza ~{_eur(max(diff, 0))} €, sotto la soglia di {_eur(thr)} €"
        text = (f"{name}: nessuna differenza apprezzabile (meno di {_eur(thr)} €): "
                f"fallo quando ti è comodo.")
    else:
        verdict = "adesso_rete"
        note = f"surplus previsto insufficiente (serve almeno {_num(cfg.margin_day12)}× il carico)"
        text = (f"{name}: nessun sole sufficiente previsto nei prossimi {cfg.max_wait_days} giorni: "
                f"fallo quando ti è comodo, ~{_eur(now_c['cost'])} €.")

    start = chosen["start"]
    return {
        "name": name, "kwh": round(E, 2), "verdict": verdict,
        "start": start.isoformat(), "end": (start + pd.Timedelta(hours=n)).isoformat(),
        "day": _day_label(start.date(), today), "window": _window(start, n),
        "cost_now": round(now_c["cost"], 3),
        "cost_best": round(best["cost"], 3) if best else None,
        "saving": round(max(diff, 0.0), 3),
        "grid_cost": round(grid_full, 3),
        "surplus_kwh": round(chosen["surplus"], 1),
        "confidence": note, "text": text,
    }


def decide(cfg: SolarConfig, sim: pd.DataFrame, price_kwh_hourly: pd.Series, now) -> list[dict]:
    """Per ogni carico: costo adesso contro la migliore finestra col sole entro max_wait_days.

    `sim` è la simulazione di base (senza il carico) da `simulate`, che parte dall'ora corrente;
    `price_kwh_hourly` è il prezzo orario previsto in €/kWh (q50)."""
    now = _ts(now)
    exp_val = export_value(_align(price_kwh_hourly, sim.index), cfg)
    base_cost, soc0 = _cost(sim, exp_val, cfg), _soc0(sim, cfg.battery)
    return [_decide_load(cfg, ld, sim, exp_val, base_cost, soc0, now) for ld in cfg.loads]


# ------------------------------------------------------------ blocco JSON

def _hour_windows(hours: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for h in sorted(set(hours)):
        if out and out[-1][1] == h:
            out[-1][1] = h + 1
        else:
            out.append([h, h + 1])
    return out


def solar_block(cfg: SolarConfig, price_hourly_mwh, now, cache_dir: Path | None = None,
                pv: pd.DataFrame | pd.Series | None = None) -> dict:
    """Blocco `solar` per data.json. `price_hourly_mwh`: Series €/MWh oppure DataFrame con q50
    (prezzi reali + previsione, Europe/Rome). `pv` serve ai test per evitare la rete."""
    now = _ts(now)
    fc = pv if pv is not None else fetch_pv_forecast(cfg, cfg.max_wait_days, cache_dir)
    pv_s = fc["pv_kwh"] if isinstance(fc, pd.DataFrame) else fc
    price = price_hourly_mwh["q50"] if isinstance(price_hourly_mwh, pd.DataFrame) else price_hourly_mwh
    horizon = pv_s[pv_s.index >= now.floor("h")]
    sim = simulate(horizon, base_series(cfg.base_load, horizon.index), cfg.battery, cfg.initial_soc)
    loads = decide(cfg, sim, price / 1000, now)

    cap, days = cfg.battery.capacity_kwh, []
    for k in range(cfg.max_wait_days + 1):
        d = now.date() + timedelta(days=k)
        day = pv_s[pv_s.index.date == d]
        if day.empty:
            continue
        s = sim[sim.index.date == d]
        full = [t.hour for t, v in s["soc"].items() if cap > 0 and v >= cap - 1e-6]
        days.append({
            "date": d.isoformat(), "label": _day_label(d, now.date()),
            "pv_kwh": round(float(day.sum()), 1),
            "surplus_kwh": round(float((day - base_series(cfg.base_load, day.index)).clip(lower=0).sum()), 1),
            "battery_full_hours": len(full), "battery_full": _hour_windows(full),
        })
    return {
        "as_of": now.isoformat(timespec="minutes"),
        "fixed_price": round(cfg.fixed_price_eur_kwh, 3),
        "ssp": cfg.ssp,
        "battery_kwh": round(cap, 1),  # 0 = nessun accumulo: la pagina non mostra "batteria piena"
        "threshold_eur": round(cfg.threshold_eur, 2),
        "days": days,
        "loads": loads,
        "attribution": ATTRIBUTION,
    }
