# Decisioni: dashboard

Collegate: [Flussi dati](decisioni-flussi-dati.md), [Preferenze](preferenze-utente.md).

- **2026-11-17** — Stile "Notte" scelto dall'utente tra due direzioni (l'altra era "Carta", chiara): fondo scuro caldo #0F1012, un solo accento lime #C8F169 che significa "costa meno", IBM Plex Sans/Mono. Scartati glassmorphism e gradienti (look "generato da AI").
- **2026-11-17** — Prezzi in €/kWh con 3 decimali; niente interruttore €/MWh.
- **2026-11-17** — Ordine richiesto dall'utente: 1) serie storica + previsione con banda; 2) 7 giorni; 3) "Fasce orarie più convenienti" in fondo. L'utente ha rifiutato "Conviene consumare": *consumare non è mai una convenienza*. Usare formulazioni neutre ("ore più economiche", "più care").
- **2026-11-17** — Intervallo di confidenza al 90% (quantili 5–95% di Timestral).
- **2026-11-17** — Medie per fascia F1 (feriali 8–19) e F2/F3 sui prossimi 30 giorni, al posto di "risparmio spostando 3 kWh".
- **2026-11-17** — Titolo "Previsione PUN". Pagina locale identica, cambia solo l'etichetta della fonte.
- **2026-11-17** — *Superata (vedi sotto).* Aggiunta la vista "3 mesi" (interruttore 30 giorni | 3 mesi) e il blocco "Prossimi 3 mesi".
- **2026-11-17** — Su richiesta dell'utente l'interruttore 30 giorni | 3 mesi (e il link `#3m`) è sostituito da quattro grafici sempre visibili, uno dopo l'altro: 7 giorni orario (ultimi 3 giorni reali), 30 giorni e 3 mesi su medie giornaliere, 12 mesi su medie settimanali con nota "oltre i 3 mesi non verificata dal backtest, solo indicativa". Se nel 12 mesi l'intervallo 90% supera il doppio del prezzo massimo (reale o mediana), l'asse si ferma lì e la nota riporta il valore massimo. "In sintesi" resta accanto ai grafici (sticky su desktop, prima dei grafici su mobile). Il blocco "Prossimi 3 mesi" resta.
- **2026-11-17** — Pagina locale: sezione "Fotovoltaico e accumulo" subito dopo il grafico iniziale (decisione dell'agente di integrazione, da confermare con l'utente): con contratto a prezzo fisso è la risposta che l'utente usa ogni giorno, mentre il resto della pagina descrive il mercato. Badge dei verdetti neutri; lime solo sul costo più basso quando la differenza supera la soglia. La pagina pubblica non cambia.
- **2026-11-17** — Il blocco "Affidabilità" nomina il modello orario in uso; se le covariate mancano e si torna al modello base, riporta le cifre di quel modello e lo dice.
- **2026-11-17** — La fascia economica di dopodomani (chip "00–06") era in IBM Plex Mono: a 12 px gli zeri puntati sembravano barrati. Passata al font sans con cifre tabulari (`num`), come la chip "più care" accanto.
- Mockup approvati (locali, non nel repo): `.superpowers/brainstorm/89197-1794872243/content/layout-v4.html`.
