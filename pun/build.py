"""Costruisce data.json e la pagina HTML per un profilo (pubblico o locale)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest as B
from . import console as K
from . import covariates as C
from . import forecast as F
from . import solar as SO
from . import sources as S

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web" / "index.html"
HOURLY_START = date(2023, 1, 1)   # contesto orario (prima c'è la crisi 2022)
DAILY_START = date(2015, 1, 1)    # contesto giornaliero: più anni per la stagionalità
DEFAULT_HOURLY = "timestral-28m"
DEFAULT_DAILY = "timestral-28m"
# varianti con covariate provate nel backtest (solo quelle con dati disponibili);
# il gas (yfinance) solo nel profilo locale, mai su GitHub Actions
COV_VARIANTS = ["timestral-28m+meteo", "timestral-28m+gas", "timestral-28m+meteo+gas"]
COV_VARIANTS_FULL = ["timestral-209m+meteo"]  # lente: non con --quick
COV_ATTRIBUTION = {"meteo": "Meteo: Open-Meteo.com (CC BY 4.0)",
                   "gas": "Gas TTF: Yahoo Finance (uso personale)"}


@dataclass
class Profile:
    name: str
    zones: dict[str, float]
    label: str
    attribution: list[str]
    out_dir: Path
    gme_dir: Path | None = None
    solar_config: Path | None = None  # "Rete o sole?": solo profilo locale
    extra: dict = field(default_factory=dict)


def profile(name: str, data_dir: Path, out: Path | None = None) -> Profile:
    if name == "public":
        return Profile(
            name="public",
            zones={"IT-North": 1.0},
            label="Prezzo Nord ≈ PUN",
            attribution=["Prezzi: Energy-Charts / Fraunhofer ISE (CC BY 4.0), zona Nord"],
            out_dir=out or ROOT / "site",
        )
    if name == "local":
        return Profile(
            name="local",
            zones=S.ZONE_WEIGHTS,
            label="PUN stimato (7 zone)",
            attribution=["Prezzi zonali: Energy-Charts / Fraunhofer ISE (uso privato)",
                         "Fonte PUN ufficiale: Gestore dei Mercati Energetici S.p.A."],
            out_dir=out or data_dir / "out",
            gme_dir=data_dir / "gme",
            solar_config=data_dir / "impianto.toml",
        )
    raise ValueError(f"profilo sconosciuto: {name}")


# ------------------------------------------------------------- calendario F1

def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


def holidays_it(y: int) -> set[date]:
    fixed = [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]
    return {date(y, m, d) for m, d in fixed} | {_easter(y) + timedelta(days=1)}


def is_f1(ts: pd.Timestamp) -> bool:
    """F1: lunedì-venerdì 8-19, festivi esclusi. Tutto il resto è F2/F3."""
    d = ts.date()
    return ts.weekday() < 5 and 8 <= ts.hour < 19 and d not in holidays_it(d.year)


# ---------------------------------------------------------------- helpers

def kwh(x):
    """€/MWh → €/kWh, arrotondato a 4 decimali (la pagina ne mostra 3)."""
    if isinstance(x, (list, tuple, np.ndarray, pd.Series)):
        return [round(float(v) / 1000, 4) for v in x]
    return round(float(x) / 1000, 4)


def windows(hours: list[int]) -> list[list[int]]:
    """Ore (0-23) → finestre contigue [inizio, fine) es. [[0, 5], [21, 24]]."""
    out: list[list[int]] = []
    for h in sorted(set(hours)):  # set: nel giorno di 25 ore l'ora 02 compare due volte
        if out and out[-1][1] == h:
            out[-1][1] = h + 1
        else:
            out.append([h, h + 1])
    return out


def day_block(values: pd.Series, kind: str, band: pd.DataFrame | None = None) -> dict:
    v = values.to_numpy()
    order = np.argsort(v)
    block = {
        "date": values.index[0].date().isoformat(),
        "kind": kind,
        "hours": kwh(v),
        # etichette dai timestamp reali: nei giorni di 23/25 ore l'indice non coincide con l'ora
        "labels": [f"{t.hour:02d}" for t in values.index],
        "mean": kwh(v.mean()),
        "cheap": windows([values.index[i].hour for i in order[:6]]),
        "dear": windows([values.index[i].hour for i in order[-6:]]),
        "min": {"v": kwh(v[order[0]]), "h": values.index[order[0]].hour},
        "max": {"v": kwh(v[order[-1]]), "h": values.index[order[-1]].hour},
    }
    if band is not None:
        b = band.loc[values.index]
        block["q05"], block["q95"] = kwh(b["q05"]), kwh(b["q95"])
        block["min"]["band"] = [kwh(b["q05"].iloc[order[0]]), kwh(b["q95"].iloc[order[0]])]
        block["max"]["band"] = [kwh(b["q05"].iloc[order[-1]]), kwh(b["q95"].iloc[order[-1]])]
    return block


# ------------------------------------------------------------------ dati

def load_prices(p: Profile, cache: Path, start: date, progress=None) -> tuple[pd.Series, str]:
    """Prezzi orari €/MWh del profilo e etichetta della fonte.

    `progress(fatti, totale, dettaglio)`: una tacca per zona (e una per i file GME).
    Le zone si scaricano una dopo l'altra: Energy-Charts limita il traffico."""
    end = date.today() + timedelta(days=1)
    gme = bool(p.gme_dir and p.gme_dir.exists())
    total = len(p.zones) + gme
    tick = progress or (lambda *a: None)
    s = S.weighted_pun(start, end, cache, p.zones, progress=lambda i, n, z: tick(i, total, z))
    label = p.label
    if gme:
        tick(len(p.zones), total, "file GME")
        g = S.gme_pun(p.gme_dir)
        g = g[g.index >= pd.Timestamp(start, tz=S.TZ)]
        if len(g):
            s = g.combine_first(s)  # il PUN ufficiale prevale dove c'è
            label = gme_label(g.index, s.index)
    tick(total, total, "")
    return s.sort_index(), label


def gme_label(gme_idx: pd.DatetimeIndex, all_idx: pd.DatetimeIndex, days: int = 90) -> str:
    """"PUN ufficiale GME" solo se i file GME coprono tutto il periodo mostrato in pagina
    (ultimi `days` giorni di storico fino all'ultima ora); altrimenti la fonte è mista."""
    end = all_idx.max()
    if gme_idx.max() >= end and gme_idx.min() <= end - pd.Timedelta(days=days):
        return "PUN ufficiale GME"
    return "PUN ufficiale GME + stima 7 zone"


def load_backtest(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def load_covariates(p: Profile, cache: Path, weather: bool = True, gas: bool = False,
                    backtest: bool = False) -> C.Covariates | None:
    """Scarica le covariate richieste; se una fonte fallisce si prosegue senza (con avviso).

    backtest=True: solo meteo osservato (usato come previsione perfetta per 16 giorni);
    altrimenti osservato + previsione Open-Meteo, emissione = adesso.
    """
    wx = load_weather(p, cache, forecast=not backtest) if weather else None
    g = load_gas(p) if gas else None
    return make_covariates(wx, g, backtest)


def load_weather(p: Profile, cache: Path, forecast: bool = True, progress=None) -> pd.DataFrame | None:
    try:
        return C.zone_weather(p.zones, cache_dir=cache, forecast=forecast, progress=progress)
    except Exception as e:  # noqa: BLE001 - rete, formato, limiti: si va avanti senza meteo
        C.warn(f"meteo Open-Meteo non disponibile ({e})")
        return None


def load_gas(p: Profile) -> pd.Series | None:
    """TTF in €/MWh, solo profilo locale (yfinance: uso personale)."""
    return C.ttf_daily(HOURLY_START - timedelta(days=60)) if p.name == "local" else None


def make_covariates(wx, g, backtest: bool = False) -> C.Covariates | None:
    if wx is None and g is None:
        return None
    return C.Covariates(weather=wx, gas=g,
                        weather_known_days=C.FORECAST_DAYS if backtest else None,
                        issue=None if backtest else pd.Timestamp.now(tz=S.TZ))


def fetch_inputs(p: Profile, cache: Path, con: K.Console, weather: bool, gas: bool,
                 forecast_weather: bool = True, pv_cfg=None) -> dict:
    """Scarica in parallelo le fonti indipendenti (siti diversi, nessun carico in più su
    ciascuno): prezzi, meteo, gas, produzione fotovoltaica. Solo i prezzi sono indispensabili."""
    n_city = len({C.ZONE_CITY[z] for z in p.zones})
    jobs = [K.Job("prices", f"Prezzi energia · {len(p.zones)} zon{'a' if len(p.zones) == 1 else 'e'}",
                  lambda t: load_prices(p, cache, DAILY_START, progress=t.update),
                  required=True, summary=lambda r: f"{r[1]} · fino al {_dm(r[0].index[-1])}")]
    if weather:
        jobs.append(K.Job("weather", f"Meteo · {n_city} città",
                          lambda t: load_weather(p, cache, forecast_weather, progress=t.update),
                          summary=lambda w: "Open-Meteo" + (" · previsione 16 giorni" if forecast_weather else "")))
    if gas and p.name == "local":
        jobs.append(K.Job("gas", "Gas TTF", lambda t: load_gas(p),
                          summary=lambda g: f"{_it(g.iloc[-1], 2)} €/MWh · {_dm(g.index[-1])}"))
    if pv_cfg is not None:
        jobs.append(K.Job("pv", "Produzione fotovoltaica", lambda t: load_pv(pv_cfg, cache),
                          summary=lambda pv: f"{_it(_pv_day(pv, 1), 1)} kWh previsti domani"))
    return con.run(jobs)


def _it(x: float, nd: int) -> str:
    return f"{x:,.{nd}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _dm(ts) -> str:
    months = "gen feb mar apr mag giu lug ago set ott nov dic".split()
    return f"{ts.day} {months[ts.month - 1]}"


def _pv_day(pv: pd.DataFrame, k: int) -> float:
    d = date.today() + timedelta(days=k)
    return float(pv["pv_kwh"][pv.index.date == d].sum())


def run_backtest(p: Profile, cache: Path, path: Path, quick: bool = False,
                 con: K.Console | None = None) -> dict:
    con = con or K.get()
    con.step("Dati per il backtest")
    got = fetch_inputs(p, cache, con, weather=True, gas=p.name == "local", forecast_weather=False)
    longrun, _ = got["prices"]
    hourly = longrun[longrun.index >= pd.Timestamp(HOURLY_START, tz=S.TZ)]
    n_h, n_d = (8, 8) if quick else (26, 24)
    h_models = ["naive-week", "mean-4w", "timestral-28m"] + ([] if quick else ["timestral-209m"])
    d_models = ["flat-28d", "seasonal-ratio", "timestral-28m"]
    registry = F.hourly_models(make_covariates(got.get("weather"), got.get("gas"), backtest=True))
    wanted = [m for m in COV_VARIANTS + ([] if quick else COV_VARIANTS_FULL)
              if p.name == "local" or not F.split_name(m)[2]]  # gas solo in locale
    skipped = [m for m in wanted if m not in registry]
    if skipped:
        C.warn(f"varianti senza dati, saltate: {', '.join(skipped)}")
    h_models += [m for m in wanted if m in registry]

    con.step("Backtest" + (" rapido" if quick else ""))
    # in fila: Timestral usa già tutti i core della CPU
    r = con.run([
        K.Job("hourly", f"Orario · {len(h_models)} modelli",
              lambda t: B.run_hourly(hourly, h_models, n_origins=n_h, registry=registry, progress=t.update),
              required=True, summary=lambda h: f"migliore: {B.pick(h, 'mae_7')}"),
        K.Job("daily", f"Giornaliero 3 mesi · {len(d_models)} modelli",
              lambda t: B.run_daily(B.daily_mean(longrun), d_models, n_origins=n_d, progress=t.update),
              required=True, summary=lambda d: f"migliore: {B.pick(d, 'mae_90')}"),
    ], parallel=False)
    res = {"as_of": date.today().isoformat(), "hourly": r["hourly"], "daily": r["daily"]}
    res["hourly_model"] = B.pick(res["hourly"], "mae_7")
    res["daily_model"] = B.pick(res["daily"], "mae_90")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


def reliability(bt: dict | None, used: str | None = None) -> dict | None:
    """Risultati del backtest per il modello orario effettivamente usato (`used`).

    Se build() è tornato al modello base perché le covariate mancavano, si riportano le
    cifre di quel modello (se è nel backtest), non quelle del modello scelto dal backtest.
    model: modello usato; figures_of: modello a cui si riferiscono le cifre; picked: scelta del backtest."""
    if not bt:
        return None
    picked = bt["hourly_model"]
    used = used or picked
    hm = used if used in bt["hourly"] else picked
    m, base = bt["hourly"][hm], bt["hourly"]["naive-week"]
    return {
        "as_of": bt["as_of"],
        "model": used,
        "figures_of": hm,
        "picked": picked,  # diverso da model se oggi le covariate non erano disponibili
        "daily_model": bt["daily_model"],
        "is_baseline": used in F.BASELINES,
        "hit6": m["hit6"],
        "coverage90": m["coverage90"],
        "mae_1": kwh(m["mae_1"]),
        "mae_30_daily": kwh(m["daily_mae_30"]),
        "gain_vs_naive": round(1 - m["mae_7"] / base["mae_7"], 3),
        "n": int(m["n"]),
        "month_mae": kwh([bt["daily"][bt["daily_model"]][f"month{i}_mae"] for i in (1, 2, 3)]),
        "coverage90_daily": bt["daily"][bt["daily_model"]]["coverage90"],
    }


# ------------------------------------------------------------------ build

def build(p: Profile, cache: Path, backtest_path: Path, con: K.Console | None = None) -> dict:
    con = con or K.get()
    bt = load_backtest(backtest_path)
    h_model = bt["hourly_model"] if bt else DEFAULT_HOURLY
    d_model = bt["daily_model"] if bt else DEFAULT_DAILY
    base, use_w, use_g = F.split_name(h_model)
    use_g = use_g and p.name == "local"
    pv_cfg = load_solar_config(p)

    # 1) dati: fonti indipendenti in parallelo. Il meteo solo se il modello lo usa; il gas
    # sempre nel profilo locale (si vede in console e nel riepilogo), nel modello solo se serve
    con.step("Dati")
    got = fetch_inputs(p, cache, con, weather=use_w, gas=p.name == "local", pv_cfg=pv_cfg)
    prices, label = got["prices"]
    hourly = B.regular_hourly(prices[prices.index >= pd.Timestamp(HOURLY_START, tz=S.TZ)])
    now = pd.Timestamp.now(tz=S.TZ)
    today = now.date()

    # ultimo giorno completo di prezzi reali (domani, se l'asta è già pubblicata)
    complete = hourly.groupby(hourly.index.date).size()
    last_day = max(d for d, n in complete.items() if n >= 23)
    hourly = hourly[hourly.index.date <= last_day]

    # se le covariate mancano, si torna al modello base
    registry = F.HOURLY
    if use_w or use_g:
        registry = F.hourly_models(make_covariates(got.get("weather"), got.get("gas")))
        if h_model not in registry:
            C.warn(f"covariate per {h_model} non disponibili: uso {base}")
            h_model, use_w, use_g = base, False, False
    cov_credits = [COV_ATTRIBUTION[k] for k, used in (("meteo", use_w), ("gas", use_g)) if used]
    daily_real = B.daily_mean(prices[prices.index.date <= last_day])

    # 2) previsioni, in fila: Timestral usa già tutti i core della CPU
    con.step("Previsione")
    fc = con.run([
        K.Job("hourly", f"Orario 31 giorni · {model_name(h_model)}",
              lambda t: registry[h_model](hourly, 31 * 24), required=True),
        K.Job("daily", f"Giornaliero 12 mesi · {model_name(d_model)}",
              lambda t: F.DAILY[d_model](daily_real, 365), required=True),
    ], parallel=False)
    fc_h, fc_d = fc["hourly"], fc["daily"]

    def hours_of(d: date, frame):
        return frame[frame.index.date == d]

    tomorrow, after = today + timedelta(days=1), today + timedelta(days=2)
    blocks = {}
    for key, d in (("tomorrow", tomorrow), ("day_after", after)):
        real = hours_of(d, hourly)
        if len(real) >= 23:
            blocks[key] = day_block(real, "actual")
        else:
            f = hours_of(d, fc_h)
            blocks[key] = day_block(f["q50"], "forecast", f)

    # 7 giorni da domani: reale se c'è, altrimenti previsione oraria
    week = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        real = hours_of(d, hourly)
        if len(real) >= 23:
            v, kind = real, "actual"
        else:
            v, kind = hours_of(d, fc_h)["q50"], "forecast"
        week.append({"date": d.isoformat(), "kind": kind, "mean": kwh(v.mean()),
                     "min": kwh(v.min()), "max": kwh(v.max())})

    # previsione giornaliera 30 giorni (dal modello orario) e 90 giorni (modello giornaliero)
    fh = fc_h.copy()
    fh["day"] = fh.index.date
    d30 = fh.groupby("day")[["q05", "q50", "q95"]].mean().iloc[:30]
    f30 = [{"d": d.isoformat(), "q05": kwh(r.q05), "q50": kwh(r.q50), "q95": kwh(r.q95)}
           for d, r in d30.iterrows()]
    f365 = [{"d": d.date().isoformat(), "q05": kwh(r.q05), "q50": kwh(r.q50), "q95": kwh(r.q95)}
            for d, r in fc_d.iterrows()]
    f90 = f365[:90]
    months = []
    for i in range(3):
        blk = fc_d.iloc[i * 30:(i + 1) * 30]
        months.append({"from": blk.index[0].date().isoformat(), "to": blk.index[-1].date().isoformat(),
                       "q05": kwh(blk.q05.mean()), "q50": kwh(blk.q50.mean()), "q95": kwh(blk.q95.mean())})

    hist = daily_real[daily_real.index.date <= min(last_day, today)].iloc[-365:]
    history = [{"d": d.date().isoformat(), "v": kwh(v)} for d, v in hist.items()]

    # grafico 7 giorni: prezzi orari reali degli ultimi 3 giorni + previsione fino a oggi+7
    recent = hourly[hourly.index.date >= today - timedelta(days=3)]
    ahead = fc_h[fc_h.index.date <= today + timedelta(days=7)]
    hourly7 = {
        "actual": [{"t": t.isoformat(), "v": kwh(v)} for t, v in recent.items()],
        "forecast": [{"t": t.isoformat(), "q05": kwh(r.q05), "q50": kwh(r.q50), "q95": kwh(r.q95)}
                     for t, r in ahead.iterrows()],
    }
    today_real = hours_of(today, hourly)
    today_mean = kwh(today_real.mean()) if len(today_real) else history[-1]["v"]

    f1 = fh.iloc[: 30 * 24]
    mask = np.array([is_f1(t) for t in f1.index])
    fasce = {
        "F1": {k: kwh(f1.loc[mask, k].mean()) for k in ("q05", "q50", "q95")},
        "F23": {k: kwh(f1.loc[~mask, k].mean()) for k in ("q05", "q50", "q95")},
    }

    data = {
        "title": "Previsione PUN",
        "profile": p.name,
        "generated_at": now.isoformat(timespec="minutes"),
        "today": today.isoformat(),
        "source_label": label,
        "attribution": p.attribution + cov_credits + ["Previsione: Timestral (Mistral AI)"],
        "today_mean": today_mean,
        "history": history,
        "forecast30": f30,
        "forecast90": f90,
        "forecast365": f365,
        "hourly7": hourly7,
        "months": months,
        "tomorrow": blocks["tomorrow"],
        "day_after": blocks["day_after"],
        "week": week,
        "fasce": fasce,
        "model": {"hourly": h_model, "daily": d_model},
        "reliability": reliability(bt, h_model),
    }
    g = got.get("gas")
    if g is not None and len(g):  # solo profilo locale: ultima chiusura TTF in €/MWh
        data["gas_ttf"] = {"eur_mwh": round(float(g.iloc[-1]), 2), "date": g.index[-1].date().isoformat()}
    if p.name == "local" and got.get("pv") is not None:
        sol = solar_section(p, cache, hourly, fc_h, today, now, cfg=pv_cfg, pv=got["pv"])
        if sol:
            data["solar"] = sol
            data["attribution"].insert(-1, sol["attribution"])
    return data


def model_name(m: str) -> str:
    """"timestral-28m+meteo" → "Timestral 28M + meteo"."""
    base, w, g = F.split_name(m)
    name = {"timestral-28m": "Timestral 28M", "timestral-209m": "Timestral 209M",
            "naive-week": "settimana precedente", "mean-4w": "media 4 settimane",
            "flat-28d": "media 28 giorni", "seasonal-ratio": "profilo stagionale"}.get(base, base)
    return name + (" + meteo" if w else "") + (" + gas" if g else "")


def load_solar_config(p: Profile):
    """Configurazione "Rete o sole?" (data/impianto.toml) o None; errori come avvisi."""
    if p.name != "local" or p.solar_config is None or not p.solar_config.exists():
        return None
    try:
        return SO.load_config(p.solar_config)
    except (SO.SolarError, ValueError, OSError) as e:  # TOMLDecodeError è un ValueError
        C.warn(f"fotovoltaico non disponibile ({e}): sezione omessa")
        return None


def load_pv(cfg, cache: Path) -> pd.DataFrame | None:
    try:
        return SO.fetch_pv_forecast(cfg, cfg.max_wait_days, cache)
    except (SO.SolarError, ValueError, OSError) as e:
        C.warn(f"fotovoltaico non disponibile ({e}): sezione omessa")
        return None


def solar_price_series(hourly: pd.Series, fc_h: pd.DataFrame, today: date) -> pd.Series:
    """Prezzi orari €/MWh da oggi: reali (oggi/domani) e poi q50 della previsione."""
    real = hourly[hourly.index.date >= today]
    fc = fc_h["q50"]
    if len(real):
        fc = fc[fc.index > real.index[-1]]
    return pd.concat([real, fc]).sort_index()


def solar_section(p: Profile, cache: Path, hourly: pd.Series, fc_h: pd.DataFrame,
                  today: date, now: pd.Timestamp, cfg=None, pv=None) -> dict | None:
    """Blocco "Rete o sole?" se esiste data/impianto.toml; mai nel profilo pubblico.
    `cfg`/`pv` già caricati (in parallelo con gli altri dati) se disponibili."""
    if p.name != "local":
        return None
    cfg = cfg or load_solar_config(p)
    if cfg is None:
        return None
    try:
        return SO.solar_block(cfg, solar_price_series(hourly, fc_h, today), now, cache_dir=cache, pv=pv)
    except (SO.SolarError, ValueError, OSError) as e:  # TOMLDecodeError è un ValueError
        C.warn(f"fotovoltaico non disponibile ({e}): sezione omessa")
        return None


def render(data: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False)
    (out_dir / "data.json").write_text(payload, encoding="utf-8")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA__", payload.replace("</", "<\\/"))
    page = out_dir / "index.html"
    page.write_text(html, encoding="utf-8")
    return page
