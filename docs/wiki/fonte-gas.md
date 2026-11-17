# Fonte: gas

Collegate: [GME](fonte-gme.md), [Flussi dati](decisioni-flussi-dati.md).

- **2026-11-17** — Nessuna fonte pubblica, giornaliera e ridistribuibile trovata per TTF o PSV (Energy-Charts non ha il gas; API commerciali; LEBA/EOSE licenza non chiara). Quindi niente gas nella pagina pubblica.
- **2026-11-17** — yfinance `TTF=F` funziona senza chiave, storico dal 2017-10-23. È uno scraper non ufficiale di Yahoo (dati ICE): solo uso personale nel flusso locale, mai su GitHub Actions.
- **2026-11-17** — TTF circa 3–6 €/MWh sotto il PSV GME nei primi giorni di novembre 2026.
- **2026-11-17** — Il gas è una covariata solo "passata" (il prezzo futuro non è noto); il meteo è "nota nel futuro".
- **2026-11-17** — Su richiesta dell'utente ("attenzione che sia in euro") `ttf_daily` legge la valuta da `history_metadata`. Quel giorno Yahoo dava `TTF=F` in **EUR** (borsa NYM): chiusura del 16 novembre 84,75 €/MWh. Se un giorno risultasse in USD, il prezzo viene diviso per `EURUSD=X` del giorno (o dell'ultimo noto); con altre valute la covariata gas viene saltata con un avviso (`to_eur`, 5 test).
