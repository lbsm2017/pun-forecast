"""Download e lettura dei dati di prezzo.

- Energy-Charts (Fraunhofer ISE): prezzi day-ahead per zona, senza chiave.
  IT-North è CC BY 4.0; le altre zone italiane sono "solo uso privato e interno"
  e vanno usate solo nel flusso locale.
- GME: file XML "Prezzi" scaricati a mano dall'utente (mai in automatico:
  i Termini d'uso del sito vietano strumenti automatici).
"""

from __future__ import annotations

import json
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import requests

TZ = "Europe/Rome"
EC_URL = "https://api.energy-charts.info/price"
USER_AGENT = "pun-forecast/0.1"

# Quote di domanda per zona, ricavate dalle stime di fabbisogno GME (campione nov 2026).
# Servono a stimare il PUN (media dei prezzi zonali pesata sulla domanda).
ZONE_WEIGHTS = {
    "IT-North": 0.584,
    "IT-Centre-North": 0.086,
    "IT-Centre-South": 0.170,
    "IT-South": 0.063,
    "IT-Calabria": 0.019,
    "IT-Sicily": 0.053,
    "IT-Sardinia": 0.025,
}


class SourceError(RuntimeError):
    pass


def _chunks(start: date, end: date):
    """Anni interi per il passato (una richiesta per anno), mesi per l'anno in corso."""
    today = date.today()
    y = start.year
    while y <= end.year:
        if y < today.year:
            yield date(y, 1, 1), date(y, 12, 31), f"{y}"
        else:
            m = date(y, 1, 1)
            while m <= min(end, date(y, 12, 31)):
                m1 = (pd.Timestamp(m) + pd.offsets.MonthEnd(0)).date()
                yield m, m1, f"{m:%Y-%m}"
                m = m1 + timedelta(days=1)
        y += 1


def _ec_request(bzn: str, start: date, end: date, retries: int = 6) -> dict:
    params = {"bzn": bzn, "start": start.isoformat(), "end": end.isoformat()}
    wait = 10.0
    for attempt in range(retries):
        try:
            r = requests.get(EC_URL, params=params, timeout=60, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as e:  # rete instabile: riprova
            err = str(e)
        else:
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:  # zona non ancora esistente in quel periodo (es. Calabria prima del 2021)
                return {}
            err = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        time.sleep(wait)
        wait = min(wait * 2, 120)
    raise SourceError(f"Energy-Charts {bzn} {start}..{end}: {err}")


def energy_charts(bzn: str, start: date, end: date, cache_dir: Path | None = None,
                  pause: float = 3.0) -> pd.Series:
    """Prezzi orari (€/MWh) per una zona, indice orario tz-aware Europe/Rome.

    Scarica per anni (passato) e mesi (anno in corso) con una pausa tra le
    richieste (il servizio limita il traffico) e salva in cache i periodi
    chiusi, così i lanci successivi scaricano solo il mese corrente.
    """
    today = date.today()
    parts = []
    for m0, m1, key in _chunks(start, end):
        if m1 < start:
            continue
        closed = m1 < today - timedelta(days=2)
        cache = cache_dir / "energy-charts" / bzn / f"{key}.json" if cache_dir else None
        if cache and closed and cache.exists():
            payload = json.loads(cache.read_text())
        else:
            # +2 giorni: include i prezzi di domani appena pubblicati
            payload = _ec_request(bzn, m0, min(m1, today + timedelta(days=2)))
            if cache and closed:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(payload))
            time.sleep(pause)
        if not payload.get("unix_seconds"):
            continue
        s = pd.Series(payload["price"], index=pd.to_datetime(payload["unix_seconds"], unit="s", utc=True),
                      dtype="float64")
        parts.append(s)
    if not parts:
        raise SourceError(f"Energy-Charts {bzn}: nessun dato")
    s = pd.concat(parts)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    # da ottobre 2025 i dati sono a 15 minuti: media oraria
    hourly = s.tz_convert(TZ).resample("1h").mean()
    lo = pd.Timestamp(start, tz=TZ)
    hi = pd.Timestamp(end + timedelta(days=1), tz=TZ)
    return hourly[(hourly.index >= lo) & (hourly.index < hi)].dropna()


def weighted_pun(start: date, end: date, cache_dir: Path | None, zones: dict[str, float],
                 progress=None) -> pd.Series:
    """PUN stimato = media dei prezzi zonali pesata sulla quota di domanda (una sola zona:
    i suoi prezzi). `progress(fatti, totale, zona)` prima di ogni zona."""
    cols = {}
    for i, z in enumerate(zones):
        if progress:
            progress(i, len(zones), z.removeprefix("IT-"))
        cols[z] = energy_charts(z, start, end, cache_dir)
    frame = pd.DataFrame(cols)
    w = pd.Series(zones)[frame.columns]
    # pesi rinormalizzati sulle zone presenti in ogni ora (la Calabria esiste dal 2021)
    present = frame.notna()
    est = (frame.fillna(0) * w).sum(axis=1) / (present * w).sum(axis=1)
    return est[present.any(axis=1)]


# ---------------------------------------------------------------- GME (locale)

def _gme_rows(xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    for el in root:
        if el.tag.endswith("schema"):
            continue
        yield {c.tag: (c.text or "").strip() for c in el}


def _iter_gme_prezzi(folder: Path):
    """Restituisce il contenuto dei file *MGPPrezzi.xml (orari), anche dentro zip."""
    for p in sorted(folder.rglob("*")):
        name = p.name
        if name.endswith("MGPPrezzi.xml"):
            yield p.read_bytes()
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.endswith("MGPPrezzi.xml"):
                        yield z.read(n)


def gme_pun(folder: Path) -> pd.Series:
    """PUN Index GME orario (€/MWh) dai file XML scaricati a mano, indice Europe/Rome."""
    values: dict[pd.Timestamp, float] = {}
    for blob in _iter_gme_prezzi(folder):
        for r in _gme_rows(blob):
            if not r.get("PUN") or not r.get("Data") or not r.get("Ora"):
                continue
            day = datetime.strptime(r["Data"], "%Y%m%d")
            # "Ora" 1..23/24/25: conta le ore reali dalla mezzanotte locale (gestisce l'ora legale)
            midnight_utc = pd.Timestamp(day).tz_localize(TZ).tz_convert("UTC")
            ts = (midnight_utc + pd.Timedelta(hours=int(r["Ora"]) - 1)).tz_convert(TZ)
            values[ts] = float(r["PUN"].replace(",", "."))
    if not values:
        return pd.Series(dtype="float64")
    return pd.Series(values).sort_index()
