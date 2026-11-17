# Preferenze dell'utente

- **2026-11-17** — Lingua di lavoro e della pagina: italiano. README in italiano con breve sezione inglese.
- **2026-11-17** — Progetto semplice, utile e pratico; non complicarlo (YAGNI). Ogni passo deve essere utilizzabile da solo.
- **2026-11-17** — Vincoli legali rigorosi: solo dati pubblici e usabili, niente credenziali, nessuna violazione di termini. Dati non ridistribuibili solo in locale.
- **2026-11-17** — Il repo contiene solo codice; licenza Apache-2.0; repo `pun-forecast` sull'account personale.
- **2026-11-17** — Vuole lavoro parallelo con agenti multipli e una wiki nel repo (`docs/wiki/`).
- **2026-11-17** — Formulazioni: mai presentare il consumo come "convenienza" (vedi [Dashboard](decisioni-dashboard.md)).
- **2026-11-17** — Flusso locale con un solo comando: `make run` (scarica i dati, lancia Timestral, rigenera la pagina); `make help` elenca i comandi (letti dai commenti `##` del `Makefile`).
- **2026-11-17** — Console: vuole avanzamento visibile (fasi numerate, barre, tempi) e i download **in parallelo**; alla fine **sempre un link cliccabile** alla pagina. Implementato in `pun/console.py` (nessuna dipendenza; OSC 8 + URL `file:///` visibile; righe semplici senza terminale, es. GitHub Actions). In parallelo girano le fonti diverse (Energy-Charts, Open-Meteo, Yahoo, Open-Meteo FV); le zone di Energy-Charts e le città di Open-Meteo restano in fila per non sovraccaricare i servizi; Timestral gira da solo perché usa già tutti i core.
- **2026-11-17** — Il prezzo del gas deve essere in euro (vedi [Gas](fonte-gas.md)).
