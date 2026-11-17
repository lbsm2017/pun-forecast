"""Covariate opzionali per Timestral: meteo (Open-Meteo) e gas TTF (yfinance, solo locale).

Si usano solo se il backtest dice che migliorano la previsione (vedi build.run_backtest).

- Meteo: Open-Meteo, senza chiave, CC BY 4.0, gratuito per uso non commerciale.
  Storico dall'archivio (una richiesta per città e anno, anni chiusi in cache),
  futuro dalla previsione a 16 giorni; oltre, climatologia (media per giorno
  dell'anno e ora degli anni passati). Una città ("capoluogo") per zona di mercato.
- Gas: chiusura giornaliera TTF (`TTF=F`) da yfinance, solo flusso locale e uso
  personale; covariata "passata" (nota solo fino all'emissione).

Tutte le covariate sono standardizzate (z-score sul contesto) prima di passarle al modello.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "pun-forecast/0.1"
VARS = ("temperature_2m", "shortwave_radiation", "wind_speed_100m")
WEATHER_START = date(2019, 1, 1)  # contesto orario dal 2023 + qualche anno per la climatologia
FORECAST_DAYS = 16
PAUSE = 3.0  # un anno di 3 variabili "pesa" ~26 chiamate: 3 s restano sotto il limite di 600/minuto
TZ = "Europe/Rome"

CITIES = {  # (latitudine, longitudine)
    "milano": (45.4642, 9.1900),
    "bologna": (44.4949, 11.3426),
    "roma": (41.9028, 12.4964),
    "napoli": (40.8518, 14.2681),
    "catanzaro": (38.9098, 16.5877),
    "palermo": (38.1157, 13.3615),
    "cagliari": (39.2238, 9.1217),
}

# Un capoluogo per zona di mercato (scelta dell'utente, 2026-11-17).
ZONE_CITY = {
    "IT-North": "milano",
    "IT-Centre-North": "bologna",
    "IT-Centre-South": "roma",
    "IT-South": "napoli",        # ASSUNZIONE: l'utente non ha indicato la città per il Sud
    "IT-Calabria": "catanzaro",  # ASSUNZIONE: l'utente non ha indicato la città per la Calabria
    "IT-Sicily": "palermo",
    "IT-Sardinia": "cagliari",
}


class CovariateError(RuntimeError):
    pass


def warn(msg: str) -> None:
    from . import console
    console.warn(msg)


# ------------------------------------------------------------------ Open-Meteo

def _get_json(url: str, params: dict, retries: int = 5, wait: float = 5.0) -> dict:
    """GET con retry e backoff su errori di rete, 429/5xx e risposte che non sono JSON.

    L'archivio a volte risponde HTTP 200 con un testo d'errore
    ("Unexpected error while streaming data"): si riprova.
    """
    err = "nessun tentativo"
    for _ in range(retries):
        try:
            r = requests.get(url, params=params, timeout=90, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:
            err = str(e)
        else:
            if r.status_code == 200:
                try:
                    payload = r.json()
                except ValueError:
                    err = f"risposta non JSON: {r.text[:80]!r}"
                else:
                    if isinstance(payload, dict) and "hourly" in payload:
                        return payload
                    err = f"risposta senza dati orari: {str(payload)[:80]}"
            elif r.status_code in (429, 500, 502, 503, 504):
                err = f"HTTP {r.status_code}"
            else:  # errore della richiesta (es. 400 con {"error": true, "reason": ...}): inutile riprovare
                raise CovariateError(f"Open-Meteo HTTP {r.status_code}: {r.text[:200]}")
        time.sleep(wait)
        wait = min(wait * 2, 120)
    raise CovariateError(f"Open-Meteo {url}: {err}")


def _frame(payload: dict) -> pd.DataFrame:
    h = payload["hourly"]
    idx = pd.to_datetime(h["time"]).tz_localize("UTC")
    df = pd.DataFrame({v: pd.to_numeric(pd.Series(h.get(v, [None] * len(idx))), errors="coerce").to_numpy()
                       for v in VARS}, index=idx, dtype="float64")
    return df[~df.index.duplicated(keep="last")]


def _params(city: str) -> dict:
    lat, lon = CITIES[city]
    return {"latitude": lat, "longitude": lon, "hourly": ",".join(VARS), "timezone": "UTC"}


def city_history(city: str, start: date, cache_dir: Path | None, pause: float = PAUSE) -> pd.DataFrame:
    """Meteo osservato orario (UTC) di una città, da `start` a oggi. Anni chiusi in cache."""
    today = date.today()
    parts = []
    for y in range(start.year, today.year + 1):
        closed = date(y, 12, 31) < today - timedelta(days=10)  # l'archivio ha qualche giorno di ritardo
        cache = cache_dir / "open-meteo" / city / f"{y}.json" if cache_dir else None
        if cache and closed and cache.exists():
            payload = json.loads(cache.read_text())
        else:
            p = _params(city) | {"start_date": f"{y}-01-01", "end_date": min(date(y, 12, 31), today).isoformat()}
            payload = _get_json(ARCHIVE_URL, p)
            if cache and closed:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(payload))
            time.sleep(pause)
        parts.append(_frame(payload))
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index()


def city_forecast(city: str) -> pd.DataFrame:
    """Previsione Open-Meteo (16 giorni) più gli ultimi 14 giorni, che l'archivio non ha ancora."""
    p = _params(city) | {"forecast_days": FORECAST_DAYS, "past_days": 14}
    return _frame(_get_json(FORECAST_URL, p))


def city_weather(city: str, start: date, cache_dir: Path | None, forecast: bool = False,
                 pause: float = PAUSE) -> pd.DataFrame:
    wx = city_history(city, start, cache_dir, pause)
    if forecast:
        wx = wx.combine_first(city_forecast(city))  # l'osservato prevale
        time.sleep(pause)
    return wx.dropna(how="all")


def weighted_mean(frames: dict[str, pd.DataFrame], weights: dict[str, float]) -> pd.DataFrame:
    """Media pesata delle città; i pesi si rinormalizzano dove un valore manca."""
    keys = list(frames)
    idx = frames[keys[0]].index
    for k in keys[1:]:
        idx = idx.union(frames[k].index)
    out = {}
    for v in VARS:
        m = pd.DataFrame({k: frames[k][v].reindex(idx) for k in keys})
        w = pd.Series({k: weights[k] for k in keys})
        present = m.notna()
        out[v] = (m.fillna(0) * w).sum(axis=1) / (present * w).sum(axis=1).replace(0, np.nan)
    return pd.DataFrame(out, index=idx)


def zone_weather(zones: dict[str, float], start: date = WEATHER_START, cache_dir: Path | None = None,
                 forecast: bool = False, pause: float = PAUSE, progress=None) -> pd.DataFrame:
    """Meteo del profilo: media dei capoluoghi delle zone, pesata come le zone.
    `progress(fatti, totale, città)` prima di ogni città."""
    weights: dict[str, float] = {}
    for zone, w in zones.items():
        weights[ZONE_CITY[zone]] = weights.get(ZONE_CITY[zone], 0.0) + w
    frames = {}
    for i, city in enumerate(weights):
        if progress:
            progress(i, len(weights), city.capitalize())
        frames[city] = city_weather(city, start, cache_dir, forecast, pause)
    if progress:
        progress(len(weights), len(weights), "")
    return weighted_mean(frames, weights)


def climatology(wx: pd.DataFrame, smooth_days: int = 7) -> pd.DataFrame:
    """Media per (giorno dell'anno, ora UTC) sugli anni disponibili, lisciata su ±smooth_days."""
    g = wx.groupby([wx.index.day_of_year, wx.index.hour]).mean()
    full = pd.MultiIndex.from_product([range(1, 367), range(24)])
    g = g.reindex(full)
    out = {}
    for c in wx.columns:
        a = g[c].to_numpy().reshape(366, 24)
        padded = np.concatenate([a[-smooth_days:], a, a[:smooth_days]])
        win = np.lib.stride_tricks.sliding_window_view(padded, 2 * smooth_days + 1, axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # finestre tutte vuote → NaN
            out[c] = np.nanmean(win, axis=-1).ravel()
    return pd.DataFrame(out, index=full)


def _clim_at(clim: pd.DataFrame, idx: pd.DatetimeIndex) -> np.ndarray:
    pos = (idx.day_of_year.to_numpy() - 1) * 24 + idx.hour.to_numpy()
    return clim.to_numpy()[pos]


# ------------------------------------------------------------------- gas TTF

def ttf_daily(start: date) -> pd.Series | None:
    """Chiusure giornaliere TTF (€/MWh) indicizzate per data di contrattazione; None se non disponibili."""
    try:
        import yfinance as yf  # opzionale: extra "local"
    except ImportError:
        warn("yfinance non installato (uv sync --extra local): niente covariata gas")
        return None
    try:
        t = yf.Ticker("TTF=F")
        s = _daily(t.history(start=start.isoformat(), interval="1d"))
        currency = (t.history_metadata or {}).get("currency")
        eurusd = None
        if currency == "USD":  # EURUSD=X = dollari per 1 euro
            eurusd = _daily(yf.Ticker("EURUSD=X").history(start=start.isoformat(), interval="1d"))
        return to_eur(s, currency, eurusd)
    except Exception as e:  # noqa: BLE001 - qualsiasi errore di yfinance: si procede senza gas
        warn(f"gas TTF non disponibile ({e})")
        return None


def _daily(h: pd.DataFrame) -> pd.Series:
    """Chiusure di yfinance -> serie per data (senza fuso), senza duplicati."""
    close = h["Close"].dropna()
    if close.empty:
        raise ValueError("serie vuota")
    s = pd.Series(close.to_numpy(dtype="float64"), index=pd.DatetimeIndex(close.index.date))
    return s[~s.index.duplicated(keep="last")].sort_index()


def to_eur(price: pd.Series, currency: str | None, eurusd: pd.Series | None = None) -> pd.Series:
    """Prezzo del gas in €/MWh. EUR: invariato; USD: diviso per il cambio EUR/USD del giorno
    (o dell'ultimo giorno noto prima). Altre valute o valuta ignota: errore, niente gas."""
    if currency == "EUR":
        return price
    if currency == "USD":
        if eurusd is None or eurusd.empty:
            raise ValueError("prezzo in USD ma cambio EUR/USD non disponibile")
        fx = eurusd.reindex(eurusd.index.union(price.index)).ffill().bfill().reindex(price.index)
        return price / fx
    raise ValueError(f"valuta del TTF inattesa: {currency!r}")


def gas_hourly(daily: pd.Series, index: pd.DatetimeIndex, issue: pd.Timestamp) -> np.ndarray:
    """Gas per ogni ora di `index`, usando solo chiusure note all'emissione.

    La chiusura del giorno d si considera nota da d+1 alle 00:00 (ora italiana); ogni
    ora prende l'ultima chiusura nota a min(ora, emissione): niente sguardi al futuro.
    """
    avail = pd.DatetimeIndex(daily.index).tz_localize(None).normalize() + pd.Timedelta(days=1)
    avail = avail.tz_localize(TZ).tz_convert("UTC").as_unit("ns").asi8
    t = np.minimum(index.tz_convert("UTC").as_unit("ns").asi8, issue.tz_convert("UTC").as_unit("ns").value)
    pos = np.searchsorted(avail, t, side="right") - 1
    vals = daily.to_numpy(dtype="float64")
    out = np.where(pos >= 0, vals[np.clip(pos, 0, None)], np.nan)
    if np.isnan(out).all():
        return out
    first = out[~np.isnan(out)][0]
    return np.where(np.isnan(out), first, out)  # inizio contesto prima del primo dato noto


# ------------------------------------------------------------- per il modello

def standardize(rows: np.ndarray, n_ctx: int) -> np.ndarray:
    """z-score di ogni riga con media e deviazione standard del contesto (primi n_ctx valori)."""
    mu = np.nanmean(rows[:, :n_ctx], axis=1, keepdims=True)
    sd = np.nanstd(rows[:, :n_ctx], axis=1, keepdims=True)
    z = (rows - mu) / np.where(sd > 1e-9, sd, 1.0)
    return np.nan_to_num(z, nan=0.0)


def _future_utc(last: pd.Timestamp, steps: int) -> pd.DatetimeIndex:
    return pd.date_range(last.tz_convert("UTC") + pd.Timedelta(hours=1), periods=steps, freq="h")


@dataclass
class Covariates:
    """Dati delle covariate e regole su cosa è noto al momento dell'emissione.

    weather: meteo orario UTC (osservato; in produzione anche la previsione Open-Meteo).
    gas: chiusure giornaliere TTF (indice = data di contrattazione).
    weather_known_days: solo backtest. Le previsioni meteo archiviate non sono
        disponibili: si usa il meteo osservato fino al giorno di emissione + 15
        (come i 16 giorni di previsione Open-Meteo), poi la climatologia. È ottimistico:
        una previsione reale sbaglia, l'osservato no. In produzione (None) si usa
        quello che c'è in `weather` (osservato + previsione), poi la climatologia.
    issue: istante di emissione; se None si ricava dal contesto (fine contesto =
        D+1 23:00 → emissione D 14:00, come nel backtest).
    """

    weather: pd.DataFrame | None = None
    gas: pd.Series | None = None
    weather_known_days: int | None = None
    issue: pd.Timestamp | None = None
    _clim: dict = field(default_factory=dict, repr=False)

    def issue_time(self, ctx_index: pd.DatetimeIndex) -> pd.Timestamp:
        if self.issue is not None:
            return self.issue
        last = ctx_index[-1].tz_convert(TZ)
        return last.normalize() - pd.Timedelta(days=1) + pd.Timedelta(hours=14)

    def _climatology(self, issue: pd.Timestamp) -> pd.DataFrame:
        key = issue.floor("D")
        if key not in self._clim:
            self._clim[key] = climatology(self.weather[self.weather.index <= issue])
        return self._clim[key]

    def known(self, ctx_index: pd.DatetimeIndex, steps: int) -> np.ndarray:
        """Meteo noto su contesto + orizzonte, forma (variabili, T + steps), standardizzato."""
        if self.weather is None:
            raise CovariateError("meteo non disponibile")
        issue = self.issue_time(ctx_index)
        ctx = ctx_index.tz_convert("UTC")
        full = ctx.append(_future_utc(ctx_index[-1], steps))
        v = self.weather.reindex(full)
        if self.weather_known_days is not None:
            known_until = issue.tz_convert(TZ).normalize() + pd.Timedelta(days=self.weather_known_days)
            v.loc[v.index >= known_until.tz_convert("UTC")] = np.nan
        v = v.interpolate(limit=6, limit_area="inside")
        clim = _clim_at(self._climatology(issue), full)
        arr = np.where(np.isnan(v.to_numpy()), clim, v.to_numpy())
        return standardize(arr.T, len(ctx))

    def past(self, ctx_index: pd.DatetimeIndex) -> np.ndarray:
        """Gas noto all'emissione, forma (1, T), standardizzato."""
        if self.gas is None:
            raise CovariateError("gas non disponibile")
        g = gas_hourly(self.gas, ctx_index, self.issue_time(ctx_index))
        return standardize(g[None, :], len(ctx_index))
