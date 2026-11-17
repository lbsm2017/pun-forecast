# Fonte: Energy-Charts (Fraunhofer ISE)

API `https://api.energy-charts.info/price?bzn=<zona>&start=&end=`, senza chiave. Collegate: [Flussi dati](decisioni-flussi-dati.md).

- **2026-11-17** — Licenza dichiarata nella risposta (`license_info`): IT-North "CC BY 4.0 … Bundesnetzagentur | SMARD.de"; IT-Centre-South e IT-Calabria "for private and internal use only … external or commercial purposes … prohibited". Per prudenza tutte le zone diverse da IT-North sono trattate come solo uso privato.
- **2026-11-17** — IT-North coincide al centesimo con la colonna NORD dei file GME (15 giorni confrontati).
- **2026-11-17** — Storico IT-North dal 2015-01-05 senza giorni mancanti; risoluzione a 15 minuti da ottobre 2025 (prima oraria).
- **2026-11-17** — Limite di traffico: HTTP 429 dopo circa 10 richieste ravvicinate. Il codice scarica per anno (passato) / mese (anno in corso), con pausa e retry, e mette in cache i periodi chiusi in `data/cache/energy-charts/`.
- **2026-11-17** — IT-Calabria restituisce 404 per il 2015 (zona istituita più tardi): trattato come periodo vuoto; la media pesata rinormalizza i pesi sulle zone presenti.
- Nomi zona verificati il 2026-11-17: IT-North, IT-Centre-North, IT-Centre-South, IT-South, IT-Calabria, IT-Sicily, IT-Sardinia.
