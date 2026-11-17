# Wiki pun-forecast

Memoria storica del progetto: decisioni, fonti, risultati. Ogni affermazione è datata; non descrive "lo stato attuale" del codice. Quando qualcosa cambia si aggiunge una nuova voce datata e la vecchia si marca *superata*.

## Decisioni
- [Flussi dati pubblico e locale](decisioni-flussi-dati.md): cosa usa la pagina pubblica e cosa il flusso locale, e perché.
- [Dashboard](decisioni-dashboard.md): stile Notte, ordine delle sezioni, unità, testi.
- [Meteo per zona](decisioni-meteo-zone.md): capoluogo usato per ogni zona di mercato.
- [Preferenze dell'utente](preferenze-utente.md): lingua, semplicità, vincoli legali.
- [Rete o sole?](decisioni-fotovoltaico.md): regola per i carichi flessibili con fotovoltaico e accumulo (solo locale).

## Ambiente di lavoro
- **2026-11-17** — Regole per agenti in `CLAUDE.md` (radice del repo) e controllo automatico `tests/test_repo_hygiene.py` contro file di dati tracciati, approvati dall'utente.

## Fonti dati
- [Energy-Charts](fonte-energy-charts.md): prezzi zonali, licenze per zona, limiti di traffico.
- [GME](fonte-gme.md): termini d'uso, formato XML, colonne PUN/NAT.
- [Open-Meteo](fonte-open-meteo.md): meteo storico e previsto, condizioni.
- [Gas](fonte-gas.md): perché non c'è gas nella pagina pubblica; TTF via yfinance in locale.

## Modello e risultati
- [Timestral](modello-timestral.md): licenza, velocità su CPU, quantili, orizzonti lunghi.
- [Backtest 2026-11-17](risultati-backtest-2026-11-17.md): primi confronti con le baseline.
