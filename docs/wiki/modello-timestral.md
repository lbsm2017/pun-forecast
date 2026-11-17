# Modello: Timestral (Mistral AI)

Collegate: [Backtest 2026-11-17](risultati-backtest-2026-11-17.md).

- **2026-11-17** — Rilasciato il 2026-10-15; taglie 5M, 28M, 123M, 209M. Codice Apache-2.0 (https://github.com/mistralai/timestral, commit fissato in `pyproject.toml`: `a534bdb`). Pesi "Modified MIT": vietato a chi supera 20 M$ di fatturato mensile; scaricati da Hugging Face a runtime, non ridistribuiti.
- **2026-11-17** — API: `TimestralForecaster.from_pretrained(id).forecast(context, prediction_length, past_covariates, known_covariates)`; restituisce 21 quantili (0,01; 0,05; 0,10…0,95; 0,99) come tensori torch. Contesto massimo 32.768 passi. Oltre 1.024 passi prevede a blocchi rialimentando la mediana → bande troppo strette: per i 3 mesi si usa un modello separato su medie giornaliere (90 passi).
- **2026-11-17** — Velocità su CPU (portatile dell'utente, contesto 32.768, orizzonte 744): 28M ≈ 1,3 s; 209M ≈ 15 s. Caricamento 28M 4 s, 209M 22 s (prima volta include download ~840 MB).
- **2026-11-17** — Su Windows Hugging Face avverte che i symlink non sono supportati: innocuo.
