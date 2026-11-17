# Previsione PUN

Previsione giornaliera del prezzo dell'elettricità all'ingrosso in Italia (PUN),
pensata per le famiglie: per vedere **in quali ore e in quali giorni
l'elettricità costa meno** (utile per programmare lavatrice, lavastoviglie,
ricarica dell'auto) e per **confrontare il prezzo atteso con le offerte a
prezzo fisso**.

La pagina mostra:

- previsione **oraria** a 1, 7 e 30 giorni;
- previsione a **3 mesi** e **12 mesi** su medie giornaliere (oltre i 3 mesi
  non è verificata dal backtest: è indicativa);
- per ogni previsione un **intervallo al 90%** (il prezzo dovrebbe cadere lì
  dentro 9 volte su 10);
- per **domani**: se i prezzi definitivi del mercato del giorno prima sono già
  pubblicati (verso le 13:00) la pagina usa quelli; la previsione parte dal
  giorno successivo.

## Due flussi

| | Pubblico | Locale |
| --- | --- | --- |
| Dove gira | GitHub Actions, pagina su GitHub Pages | Sul tuo PC |
| Comando | `uv run pun build --profile public` | `uv run pun build --profile local` |
| Prezzi | Energy-Charts, solo zona **IT-North** (CC BY 4.0) | Energy-Charts, tutte le **7 zone** italiane |
| Cosa mostra | "Prezzo Nord ≈ PUN" | PUN stimato come media delle zone pesata sulla domanda |
| Errore medio vs PUN ufficiale¹ | 5,9 €/MWh | 0,55 €/MWh |
| PUN ufficiale GME | no | opzionale, da file scaricati a mano (vedi sotto) |
| Output | `site/index.html` | `data/out/index.html` |
| Si può pubblicare? | sì | **no**: solo uso privato |

¹ Errore medio assoluto su un campione di 15 giorni.

**Flusso locale e dati GME.** Le zone diverse da IT-North sono concesse da
Energy-Charts solo per uso privato e interno: il risultato del flusso locale
non va mai pubblicato. Se vuoi il PUN ufficiale, scarica a mano i file XML
"Prezzi" da [mercatoelettrico.org](https://www.mercatoelettrico.org) e
mettili in `data/gme/` (vanno bene sia gli `.xml` `*MGPPrezzi.xml` sia gli
`.zip` che li contengono). Dove c'è il PUN ufficiale prevale sulla stima.

## Comandi

Serve [uv](https://docs.astral.sh/uv/).

```sh
uv sync                                      # dipendenze (aggiungi --extra local per yfinance)
uv run pun backtest --profile public         # backtest dei modelli (--quick per una prova veloce)
uv run pun build --profile public            # pagina pubblica in site/
uv run pun build --profile local             # pagina privata in data/out/
```

Con `make` installato bastano le scorciatoie del `Makefile` (`make help` le
elenca): `make run` (pagina locale: scarica in parallelo prezzi, meteo, gas e
produzione fotovoltaica, lancia Timestral e rigenera `data/out/index.html`),
`make public`, `make backtest` (locale, circa un'ora), `make test`. In console
si vedono le fasi, l'avanzamento di ogni download e, alla fine, il link
cliccabile alla pagina.

`pun build` rifà da solo il backtest se manca o ha più di 7 giorni
(`--max-backtest-age`). Il primo avvio scarica lo storico dei prezzi dal 2015
e i pesi del modello, quindi è lento; i lanci successivi usano la cache in
`data/cache/`.

## Come funziona

- **Modello**: [Timestral](https://github.com/mistralai/timestral) di Mistral
  AI, usato zero-shot (senza addestramento) su CPU. Contesto orario dal 2023,
  contesto giornaliero dal 2015.
- **Confronto con metodi semplici**: un backtest sugli ultimi mesi confronta
  Timestral con alcune baseline: "uguale alla settimana scorsa", media delle
  ultime 4 settimane, media degli ultimi 28 giorni, profilo stagionale.
  Viene usato automaticamente il metodo con l'errore più basso.
- **Meteo** ([Open-Meteo](https://open-meteo.com)): temperatura, radiazione e
  vento di un capoluogo per zona (Nord Milano, Centro-Nord Bologna, Centro-Sud
  Roma, Sud Napoli, Calabria Catanzaro, Sicilia Palermo, Sardegna Cagliari;
  la pagina pubblica usa solo Milano). Si usa solo se il backtest dice che
  aiuta: al 2026-11-17 ha ridotto l'errore a 7 giorni di circa il 7%, ma quel
  backtest usa il meteo reale al posto delle previsioni, quindi il guadagno
  vero è minore (stima 3–5%).
- **Gas** (TTF via yfinance): solo nel flusso locale; nel backtest aggiunge
  quasi nulla.
- **Affidabilità**: la pagina riporta i risultati del backtest, tra cui quante
  delle 6 ore più economiche vengono indovinate e quante volte il prezzo reale
  cade nell'intervallo al 90%.

## Fotovoltaico e accumulo (solo locale)

Se hai pannelli e batteria, copia `impianto.example.toml` in
`data/impianto.toml` e metti i dati del tuo impianto (posizione, kWp,
inclinazione, orientamento, batteria). La sezione "Fotovoltaico e accumulo"
della pagina locale mostra la produzione prevista (Open-Meteo) per oggi e i 3
giorni dopo, il surplus oltre il consumo di base e le ore in cui la batteria
dovrebbe essere piena. `data/impianto.toml` è escluso da git: non finisce mai
nel repository né nella pagina pubblica.

## Pubblica la tua copia

1. Fai un fork del repository.
2. Settings → Pages → Source: **GitHub Actions**.
3. Nella scheda Actions abilita i workflow (nei fork sono disattivati) e lancia
   a mano "Previsione PUN giornaliera" (*Run workflow*).

Poi il workflow `.github/workflows/daily.yml` gira ogni giorno alle 13:00 UTC
(14:00 ora solare, 15:00 ora legale) e di nuovo alle 15:30 UTC, per prendere i
prezzi definitivi se sono usciti in ritardo; se fallisce, riprova una volta
dopo 10 minuti. GitHub sospende i workflow pianificati dei repository senza attività
da 60 giorni: in quel caso riattivalo dalla scheda Actions.

## Dati e licenze

Il repository **non contiene dati**: la cartella `data/` è esclusa da git.

| Componente | Licenza / condizioni |
| --- | --- |
| Codice di questo progetto | Apache-2.0 (vedi [LICENSE](LICENSE)) |
| Timestral, codice | Apache-2.0 |
| Timestral, pesi | "Modified MIT": non ammesso per aziende con ricavi oltre 20 milioni di USD al mese. I pesi si scaricano da Hugging Face al momento dell'uso, non sono ridistribuiti qui. |
| Energy-Charts / Fraunhofer ISE | Zona IT-North: CC BY 4.0. Altre zone italiane: "solo uso privato e interno" (solo flusso locale). |
| Open-Meteo (meteo; previsione fotovoltaica nel flusso locale) | CC BY 4.0, gratuito per uso non commerciale |
| GME | I termini del sito consentono l'uso personale non commerciale con l'attribuzione "Fonte: Gestore dei Mercati Energetici S.p.A." e vietano bot, scraper e strumenti automatici. Questo progetto **non scarica mai nulla dal GME in automatico**: i file li scarichi tu. |
| Prezzo del gas TTF (yfinance) | Solo flusso locale, uso personale |

## Avvertenza

È una previsione statistica, non una consulenza commerciale. Il prezzo in
bolletta è diverso dal PUN: comprende oneri di sistema, trasporto, imposte e
il margine del venditore.

---

## English

**Previsione PUN** is a daily forecast of the Italian wholesale electricity
price (PUN) for households: hourly forecasts for 1, 7 and 30 days and daily
averages for 3 months, each with a 90% interval. It shows which hours and
days are cheaper and helps compare against fixed-price offers. "Tomorrow" shows the
official day-ahead prices once published (~13:00); the forecast starts the
day after.

- **Public flow** (GitHub Actions + Pages, `uv run pun build --profile public`,
  output in `site/`): Energy-Charts zone IT-North only (CC BY 4.0), shown as
  "Prezzo Nord ≈ PUN" (mean absolute error 5.9 €/MWh vs the official PUN on a
  15-day sample).
- **Local flow** (your PC, `uv run pun build --profile local`, output in
  `data/out/`): all 7 Italian zones from Energy-Charts (private/internal use
  only, never publish), PUN estimated as a demand-weighted average (0.55 €/MWh
  error on the same sample). Optionally drop official GME `MGPPrezzi` XML/zip
  files, downloaded manually from mercatoelettrico.org, into `data/gme/`. GME
  data is never downloaded automatically (its terms forbid automated tools).
- **Model**: Mistral's Timestral, zero-shot on CPU, backtested against simple
  baselines; the lowest-error method is used and its backtest reliability is
  shown on the page. Weather (Open-Meteo, one main city per market zone) is
  used only when the backtest shows it helps (about −7% 7-day error on
  2026-11-17 with actual weather in place of forecasts, so the real gain is
  smaller, est. 3–5%). Gas (TTF via yfinance) is local-only and adds almost
  nothing.
- **Solar and battery (local only)**: copy `impianto.example.toml` to
  `data/impianto.toml` (never committed) to see the forecast PV production,
  surplus and battery-full hours for today and the next 3 days.
- **Your own copy**: fork, set Settings → Pages → Source to "GitHub Actions",
  enable Actions and run the workflow manually.
- **Licences**: code Apache-2.0. Timestral weights are under a "Modified MIT"
  licence (not for companies above USD 20M monthly revenue) and are downloaded
  from Hugging Face at runtime. The repository contains no data.

This is a statistical forecast, not commercial advice. Your bill price also
includes system charges, transport and taxes.
