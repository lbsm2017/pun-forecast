# data/

Cartella per i **dati locali**, che restano solo sul tuo PC:

- `cache/`: prezzi già scaricati da Energy-Charts;
- `backtest-public.json`, `backtest-local.json`: ultimo backtest dei modelli;
- `gme/`: file XML o zip "MGPPrezzi" scaricati a mano da mercatoelettrico.org
  (facoltativi, solo flusso locale);
- `out/`: pagina generata dal flusso locale (`data/out/index.html`).

Tutto il contenuto è escluso da git tranne questo README. **Non committare e
non pubblicare mai** i dati di questa cartella: alcune fonti sono concesse solo
per uso privato.
