# Regole per chi lavora su questo repo (persone e agenti)

Progetto: previsione del prezzo dell'elettricità (PUN) con Timestral; pagina pubblica su GitHub Pages e flusso locale privato. Leggi prima `README.md` e `docs/wiki/index.md`.

## Vincoli non negoziabili
1. **Mai dati nel repo.** Niente prezzi, cache, file GME, output, configurazioni personali (`data/` e `site/` sono git-ignored). `tests/test_repo_hygiene.py` fallisce se un file di dati è tracciato.
2. **Mai chiamate automatiche ai siti GME** (mercatoelettrico.org): i Termini d'uso (§6-bis) vietano bot e scraper. I file GME li scarica l'utente a mano in `data/gme/`. Niente API GME.
3. **Zone Energy-Charts diverse da IT-North: solo flusso locale** ("private and internal use only"). La pagina pubblica usa solo IT-North (CC BY 4.0).
4. **yfinance (gas TTF) e Open-Meteo**: solo uso non commerciale; yfinance solo in locale, mai su GitHub Actions.
5. **Covariate e modelli si tengono solo se il backtest migliora** (`pun backtest`); scelta automatica con `backtest.pick`.

## Modo di lavorare
- Ambiente: `uv sync --extra local`; test: `uv run --group dev pytest -q` (offline, senza rete e senza caricare Timestral). Tutti verdi prima di chiudere un lavoro.
- Richieste di rete gentili: pause, retry con backoff, cache dei periodi chiusi in `data/cache/`.
- Testi della pagina in italiano, formulazioni neutre: il consumo non è mai presentato come "convenienza" (es. "ore più economiche", non "conviene consumare").
- Prezzi in pagina in €/kWh con 3 decimali; intervallo 90% (quantili 5–95%).
- Semplicità prima di tutto: niente nuove dipendenze pesanti, niente framework web.
- Commit e pubblicazione solo su richiesta esplicita dell'utente.

## Wiki (`docs/wiki/`)
Memoria storica del progetto. Ogni affermazione è datata ("Il 2026-11-17 l'utente ha deciso…"); quando qualcosa cambia si aggiunge una nuova voce e la vecchia si marca *superata*. Aggiorna `index.md` quando aggiungi una pagina.
