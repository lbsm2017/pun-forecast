"""Backtest: simula le previsioni del passato e misura quanto sono state utili.

Ogni "emissione" avviene il giorno D alle 14: i prezzi sono noti fino alla fine
di D+1 (l'asta di D+1 è già chiusa), la previsione parte da D+2.

Metriche (prezzi in €/MWh nei calcoli, €/kWh in pagina):
- mae_*: errore assoluto medio orario sul primo giorno, 7 giorni, 30 giorni
- daily_mae_*: errore medio sulle medie giornaliere
- coverage90: quota di valori reali dentro l'intervallo 90% (ideale ~0,90)
- hit6: quante delle 6 ore indicate come più economiche del primo giorno
  previsto lo sono davvero (0-1)
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from . import forecast as F

H30 = 30 * 24


def regular_hourly(s: pd.Series) -> pd.Series:
    """Serie oraria senza buchi (buchi brevi interpolati)."""
    utc = s.tz_convert("UTC")
    full = utc.reindex(pd.date_range(utc.index[0], utc.index[-1], freq="h"))
    full = full.interpolate(limit=6).ffill().bfill()
    return full.tz_convert(s.index.tz)


def daily_mean(s: pd.Series) -> pd.Series:
    """Medie giornaliere su giorni civili italiani, indice di date senza fuso."""
    d = s.groupby(s.index.date).mean()
    d.index = pd.DatetimeIndex(pd.to_datetime(d.index))
    return d.asfreq("D").interpolate(limit=3).ffill()


def _cheap_hit(pred: np.ndarray, real: np.ndarray, k: int = 6) -> float:
    return len(set(np.argsort(pred)[:k]) & set(np.argsort(real)[:k])) / k


def hourly_origins(series: pd.Series, n: int, step_days: int = 7) -> list[int]:
    """Posizioni (fine del contesto) delle emissioni simulate, dalla più recente."""
    hours = series.index
    last_ok = len(hours) - H30 - 1
    # fine contesto = ultima ora di D+1 → la successiva è la mezzanotte
    ends = [i for i in range(len(hours) - 1) if hours[i + 1].hour == 0 and i <= last_ok]
    ends = ends[::-1][::step_days][:n]
    return sorted(ends)


def run_hourly(series: pd.Series, models: list[str], n_origins: int = 26, step_days: int = 7,
               min_context: int = 24 * 365, registry: dict | None = None, progress=None) -> dict:
    """`registry`: nome → funzione (default F.HOURLY; con covariate F.hourly_models(cov)).
    `progress(fatti, totale, modello)` prima di ogni previsione."""
    registry = F.HOURLY if registry is None else registry
    series = regular_hourly(series)
    origins = [e for e in hourly_origins(series, n_origins, step_days) if e >= min_context]
    out, step, total = {}, 0, len(models) * len(origins)
    for name in models:
        t0 = time.time()
        rows = []
        for end in origins:
            if progress:
                progress(step, total, name)
            step += 1
            hist = series.iloc[: end + 1]
            fc = registry[name](hist, H30)
            real = series.iloc[end + 1 : end + 1 + H30].to_numpy()
            q50, q05, q95 = fc["q50"].to_numpy(), fc["q05"].to_numpy(), fc["q95"].to_numpy()
            err = np.abs(q50 - real)
            d_pred = q50.reshape(30, 24).mean(axis=1)
            d_real = real.reshape(30, 24).mean(axis=1) if len(real) == H30 else None
            rows.append({
                "mae_1": err[:24].mean(), "mae_7": err[: 7 * 24].mean(), "mae_30": err.mean(),
                "daily_mae_30": np.abs(d_pred - d_real).mean(),
                "coverage90": ((real >= q05) & (real <= q95)).mean(),
                "hit6": _cheap_hit(q50[:24], real[:24]),
            })
        df = pd.DataFrame(rows)
        out[name] = {k: round(float(v), 4) for k, v in df.mean().items()}
        out[name]["n"] = len(df)
        out[name]["seconds"] = round(time.time() - t0, 1)
    return out


def run_daily(daily: pd.Series, models: list[str], n_origins: int = 24, step_days: int = 14,
              horizon: int = 90, progress=None) -> dict:
    last_ok = len(daily) - horizon - 2
    ends = list(range(last_ok, 3 * 365, -step_days))[:n_origins][::-1]
    out, step, total = {}, 0, len(models) * len(ends)
    for name in models:
        t0 = time.time()
        rows = []
        for end in ends:
            if progress:
                progress(step, total, name)
            step += 1
            hist = daily.iloc[: end + 1]
            fc = F.DAILY[name](hist, horizon)
            real = daily.iloc[end + 1 : end + 1 + horizon].to_numpy()
            q50, q05, q95 = fc["q50"].to_numpy(), fc["q05"].to_numpy(), fc["q95"].to_numpy()
            err = np.abs(q50 - real)
            # errore sulla media di ciascun mese (blocchi da 30 giorni)
            m_err = [abs(q50[i:i + 30].mean() - real[i:i + 30].mean()) for i in (0, 30, 60)]
            rows.append({
                "mae_30": err[:30].mean(), "mae_90": err.mean(),
                "month1_mae": m_err[0], "month2_mae": m_err[1], "month3_mae": m_err[2],
                "coverage90": ((real >= q05) & (real <= q95)).mean(),
            })
        df = pd.DataFrame(rows)
        out[name] = {k: round(float(v), 4) for k, v in df.mean().items()}
        out[name]["n"] = len(df)
        out[name]["seconds"] = round(time.time() - t0, 1)
    return out


def pick(results: dict, metric: str) -> str:
    """Il modello con l'errore più basso sulla metrica scelta."""
    return min(results, key=lambda m: results[m][metric])
