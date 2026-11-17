"""Modelli di previsione: Timestral (zero-shot) e due baseline semplici per confronto.

Tutte le funzioni ricevono la serie storica fino all'istante di emissione e
restituiscono un DataFrame con colonne q05, q50, q95 (intervallo 90%).
- Orario: fino a 30+ giorni, risoluzione oraria.
- Giornaliero: fino a 90 giorni sulle medie giornaliere, con storico lungo
  (dal 2015) per cogliere la stagionalità annuale.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

QUANTILES = (0.05, 0.5, 0.95)
COLS = ("q05", "q50", "q95")
MAX_CONTEXT = 32768


@lru_cache(maxsize=4)
def _load(model_id: str):
    from timestral import TimestralForecaster  # import lento: solo se serve

    return TimestralForecaster.from_pretrained(model_id)


def _future_index(last: pd.Timestamp, steps: int, freq: str) -> pd.DatetimeIndex:
    if freq == "h":
        # passo in UTC per attraversare correttamente i cambi d'ora
        start = last.tz_convert("UTC") + pd.Timedelta(hours=1)
        return pd.date_range(start, periods=steps, freq="h").tz_convert(last.tz)
    return pd.date_range(last + pd.Timedelta(days=1), periods=steps, freq="D")


def timestral(history: pd.Series, steps: int, freq: str, model_id: str) -> pd.DataFrame:
    """Previsione probabilistica zero-shot. `history` deve essere regolare (senza buchi)."""
    ctx = history.to_numpy(dtype="float64")[-MAX_CONTEXT:]
    fc = _load(model_id).forecast(ctx, prediction_length=steps)
    levels = list(fc.quantile_levels)
    q = np.asarray(fc.quantiles)[0, 0]  # (steps, n_levels)
    data = {c: q[:, levels.index(lv)] for c, lv in zip(COLS, QUANTILES)}
    return pd.DataFrame(data, index=_future_index(history.index[-1], steps, freq))


def timestral_cov(history: pd.Series, steps: int, model_id: str, cov, weather: bool, gas: bool) -> pd.DataFrame:
    """Timestral orario con covariate: meteo noto anche nel futuro, gas solo passato.

    `cov` è un `covariates.Covariates`; le covariate sono costruite sul contesto
    effettivamente usato (ultimi MAX_CONTEXT valori) e standardizzate lì.
    """
    hist = history.iloc[-MAX_CONTEXT:]
    kw = {}
    if weather:
        kw["known_covariates"] = cov.known(hist.index, steps)[None]
    if gas:
        kw["past_covariates"] = cov.past(hist.index)[None]
    fc = _load(model_id).forecast(hist.to_numpy(dtype="float64"), prediction_length=steps, **kw)
    levels = list(fc.quantile_levels)
    q = np.asarray(fc.quantiles)[0, 0]
    data = {c: q[:, levels.index(lv)] for c, lv in zip(COLS, QUANTILES)}
    return pd.DataFrame(data, index=_future_index(history.index[-1], steps, "h"))


def _band_from_errors(point: np.ndarray, errors: np.ndarray, index) -> pd.DataFrame:
    lo, hi = np.nanquantile(errors, [0.05, 0.95])
    return pd.DataFrame({"q05": point + lo, "q50": point, "q95": point + hi}, index=index)


def naive_week(history: pd.Series, steps: int) -> pd.DataFrame:
    """Orario: "uguale alla settimana scorsa", ripetuto per tutto l'orizzonte."""
    last_week = history.to_numpy()[-168:]
    point = np.resize(last_week, steps)
    y = history.to_numpy()[-24 * 180:]
    errors = y[168:] - y[:-168]
    return _band_from_errors(point, errors, _future_index(history.index[-1], steps, "h"))


def mean_4w(history: pd.Series, steps: int) -> pd.DataFrame:
    """Orario: media delle ultime 4 settimane per la stessa ora della settimana."""
    y = history.to_numpy()[-168 * 4:].reshape(4, 168)
    profile = y.mean(axis=0)
    point = np.resize(profile, steps)
    hist = history.to_numpy()[-24 * 180:]
    # errore "in campione": il profilo va allineato alla fase settimanale della
    # fine della serie (il profilo inizia 168*4 ore prima dell'ultima ora + 1)
    n = len(hist) - 168 * 4
    phase = (-n) % 168
    errors = hist[168 * 4:] - np.resize(np.roll(profile, -phase), n)
    return _band_from_errors(point, errors, _future_index(history.index[-1], steps, "h"))


def flat_28d(history: pd.Series, steps: int) -> pd.DataFrame:
    """Giornaliero: la media degli ultimi 28 giorni resta costante."""
    point = np.full(steps, history.iloc[-28:].mean())
    y = history.to_numpy()
    roll = pd.Series(y).rolling(28).mean().to_numpy()
    # errore storico di "media 28 giorni" a orizzonte medio (45 giorni)
    errors = y[28 + 45:] - roll[27:-46]
    return _band_from_errors(point, errors[-730:], _future_index(history.index[-1], steps, "D"))


def seasonal_ratio(history: pd.Series, steps: int) -> pd.DataFrame:
    """Giornaliero: media degli ultimi 28 giorni x profilo stagionale medio degli anni passati.

    Il profilo è il rapporto tra il prezzo del giorno dell'anno e la media dei 28
    giorni precedenti la data di emissione, mediato sugli anni disponibili.
    """
    last = history.index[-1]
    base = history.iloc[-28:].mean()
    idx = _future_index(last, steps, "D")
    ratios = []
    for years_back in range(1, 11):
        origin = last - pd.DateOffset(years=years_back)
        past_base = history[(history.index > origin - pd.Timedelta(days=28)) & (history.index <= origin)]
        fut = history.reindex(idx - pd.DateOffset(years=years_back))
        if len(past_base) < 20 or fut.isna().mean() > 0.1:
            continue
        ratios.append(fut.to_numpy() / past_base.mean())
    profile = np.nanmedian(np.vstack(ratios), axis=0) if ratios else np.ones(steps)
    point = base * profile
    spread = np.nanquantile(np.vstack(ratios), [0.05, 0.95], axis=0) * base if len(ratios) >= 3 else None
    df = pd.DataFrame({"q05": point * 0.75, "q50": point, "q95": point * 1.25}, index=idx)
    if spread is not None:
        df["q05"], df["q95"] = np.minimum(spread[0], point), np.maximum(spread[1], point)
    return df


HOURLY = {
    "timestral-28m": lambda h, n: timestral(h, n, "h", "mistralai/Timestral-28M"),
    "timestral-209m": lambda h, n: timestral(h, n, "h", "mistralai/Timestral-209M"),
    "naive-week": naive_week,
    "mean-4w": mean_4w,
}

DAILY = {
    "timestral-28m": lambda h, n: timestral(h, n, "D", "mistralai/Timestral-28M"),
    "timestral-209m": lambda h, n: timestral(h, n, "D", "mistralai/Timestral-209M"),
    "flat-28d": flat_28d,
    "seasonal-ratio": seasonal_ratio,
}

BASELINES = {"naive-week", "mean-4w", "flat-28d", "seasonal-ratio"}

# Varianti orarie con covariate: "<modello>+meteo", "+gas", "+meteo+gas".
TIMESTRAL_IDS = {"timestral-28m": "mistralai/Timestral-28M", "timestral-209m": "mistralai/Timestral-209M"}
COV_TAGS = {"+meteo": (True, False), "+gas": (False, True), "+meteo+gas": (True, True)}


def split_name(name: str) -> tuple[str, bool, bool]:
    """"timestral-28m+meteo+gas" → ("timestral-28m", usa meteo, usa gas)."""
    base, _, rest = name.partition("+")
    tags = set(rest.split("+")) if rest else set()
    return base, "meteo" in tags, "gas" in tags


def hourly_models(cov=None) -> dict:
    """HOURLY più le varianti con covariate disponibili in `cov` (covariates.Covariates)."""
    models = dict(HOURLY)
    if cov is None:
        return models
    for base, model_id in TIMESTRAL_IDS.items():
        for tag, (w, g) in COV_TAGS.items():
            if (w and cov.weather is None) or (g and cov.gas is None):
                continue
            models[base + tag] = (lambda h, n, mid=model_id, w=w, g=g:
                                  timestral_cov(h, n, mid, cov, weather=w, gas=g))
    return models
