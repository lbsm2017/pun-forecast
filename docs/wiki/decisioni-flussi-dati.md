# Decisioni: flussi dati

Collegate: [Energy-Charts](fonte-energy-charts.md), [GME](fonte-gme.md), [Gas](fonte-gas.md), [Meteo per zona](decisioni-meteo-zone.md).

- **2026-11-17** — L'utente vuole solo dati pubblici, senza credenziali e senza violare termini d'uso. Il repo contiene solo codice, mai dati (`data/` è in `.gitignore`).
- **2026-11-17** — Due flussi con lo stesso codice:
  - *Pubblico* (GitHub Actions + Pages, deploy diretto, nessun branch gh-pages): Energy-Charts zona IT-North (CC BY 4.0), etichetta "Prezzo Nord ≈ PUN"; meteo Milano; nessun gas.
  - *Locale* (PC utente, on demand): Energy-Charts 7 zone (consentito solo uso privato) → PUN stimato con pesi di domanda; file GME scaricati a mano in `data/gme/` facoltativi e prevalenti; gas TTF da yfinance.
- **2026-11-17** — Scartate: download automatico da GME (vietato dai termini, §6-bis) e API GME (l'utente non la vuole, richiede registrazione).
- **2026-11-17** — "Domani" mostra i prezzi definitivi quando l'asta è pubblicata (~13:00); la previsione parte da dopodomani. Il workflow gira alle 13:00 e 15:30 UTC.
- **2026-11-17** — Errore della stima rispetto al PUN ufficiale su 360 ore (3–17 nov 2026, file GME dell'utente): solo Nord 5,91 €/MWh; 7 zone pesate 0,55 €/MWh (95° percentile 38,8 contro 3,6).
- **2026-11-17** — Orizzonti: orario fino a 30 giorni; aggiunta su richiesta dell'utente una previsione a 3 mesi su medie giornaliere (storico dal 2015 per la stagionalità annuale).
