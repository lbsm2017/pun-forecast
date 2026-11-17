# Fonte: Open-Meteo

Collegate: [Meteo per zona](decisioni-meteo-zone.md).

- **2026-11-17** — Termini (https://open-meteo.com/en/terms): gratuito per uso non commerciale, dati CC BY 4.0, limiti < 10.000 chiamate/giorno, 5.000/ora, 600/minuto. Il progetto è non commerciale.
- **2026-11-17** — Archivio storico (`archive-api.open-meteo.com/v1/archive`) e previsione a 16 giorni (`api.open-meteo.com/v1/forecast`) funzionano senza chiave.
- **2026-11-17** — Problema ricorrente: l'archivio a volte risponde con errori del server (HTTP 500 o 200 con testo "Unexpected error while streaming data: fileModifiedOrPrevalidationFailed"). Richieste per anno e retry li aggirano quasi sempre; Bologna 2026 è fallita più volte di fila quel giorno.
