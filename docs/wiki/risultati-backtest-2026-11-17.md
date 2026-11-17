# Risultati: backtest del 2026-11-17

Collegate: [Timestral](modello-timestral.md), [Dashboard](decisioni-dashboard.md).

Serie: Energy-Charts IT-North. Emissione simulata il giorno D alle 14 con prezzi noti fino a fine D+1; previsione da D+2. Errori in €/MWh. Codice: `pun/backtest.py` (albero di lavoro non ancora committato al 2026-11-17).

## Orario (26 emissioni settimanali nell'ultimo anno, contesto dal 2023)
| Modello | MAE 1° giorno | MAE 7 gg | MAE 30 gg | Copertura 90% | Ore economiche giuste (su 1) |
|---|---|---|---|---|---|
| uguale alla settimana scorsa | 18,2 | 20,4 | 25,9 | 0,84 | 0,65 |
| media 4 settimane | 18,7 | 20,1 | 26,3 | 0,79 | 0,67 |
| Timestral-28M | 13,2 | 16,4 | 23,7 | 0,85 | 0,71 |
| Timestral-209M | 12,1 | 15,3 | 22,9 | 0,88 | 0,74 |

## Giornaliero 3 mesi (24 emissioni ogni 14 giorni, contesto dal 2015)
| Modello | MAE 30 gg | MAE 90 gg | Copertura 90% |
|---|---|---|---|
| media 28 giorni | 19,1 | 25,7 | 0,73 |
| profilo stagionale | 17,8 | 23,0 | 0,87 |
| Timestral-28M | 14,9 | 20,3 | 0,93 |
| Timestral-209M | 15,1 | 21,8 | 0,91 |

## Prototipo covariate (2026-11-17, script temporaneo `covtest.py`, non nel repo)
Timestral-28M orario, IT-North, stesse 26 emissioni. Meteo = media Milano/Torino/Venezia/Bologna (Bologna senza 2026), **valori reali** per i primi 16 giorni (ottimistico: simula una previsione perfetta) e climatologia dopo. Gas = TTF yfinance del giorno prima.

| Covariate | MAE 1° giorno | MAE 7 gg | MAE 30 gg | Copertura 90% | hit6 |
|---|---|---|---|---|---|
| nessuna | 13,2 | 16,4 | 23,7 | 0,85 | 0,71 |
| meteo | 12,9 | 15,3 | 22,9 | 0,89 | 0,71 |
| gas | 13,0 | 16,2 | 23,5 | 0,86 | 0,71 |
| meteo + gas | 12,9 | 15,3 | 22,9 | 0,88 | 0,72 |

Lettura: il meteo migliora la settimana di circa il 6–7% e la copertura della banda (limite superiore, per via del meteo "perfetto"); il gas aggiunge poco. La misura ufficiale con le città capoluogo è affidata all'agente covariate.

## Misura ufficiale covariate (2026-11-17, report dell'agente covariate; `pun/covariates.py`, albero non committato)
Capoluogo per zona (vedi [Meteo per zona](decisioni-meteo-zone.md)); meteo reale fino a emissione + 15 giorni, poi climatologia ±7 giorni senza look-ahead; 26 emissioni.

Profilo pubblico (IT-North), da `data/backtest-public.json` rigenerato:

| Modello | MAE 1° g | MAE 7 gg | MAE 30 gg | Copertura 90% | hit6 |
|---|---|---|---|---|---|
| naive-week | 18,22 | 20,41 | 25,88 | 0,84 | 0,65 |
| mean-4w (banda corretta) | 18,72 | 20,15 | 26,25 | 0,60 | 0,67 |
| timestral-28m | 13,17 | 16,41 | 23,71 | 0,85 | 0,71 |
| timestral-209m | 12,10 | 15,31 | 22,88 | 0,88 | 0,74 |
| timestral-28m+meteo | 13,05 | 15,31 | 23,05 | 0,88 | 0,71 |
| **timestral-209m+meteo** (scelto) | **11,78** | **14,17** | 22,81 | 0,88 | **0,77** |

Profilo locale (7 zone): 28m 16,74 → 28m+meteo 15,28 (MAE 7 gg); gas +0,8% da solo, nulla sopra il meteo.
Senza alcuna previsione meteo (solo climatologia) il guadagno del meteo su 28m scende al 2,1%: il guadagno reale con le previsioni Open-Meteo è stimato 3–5%.
Costo: backtest settimanale pubblico ≈ 47 min CPU (209m+meteo ≈ 65 s a previsione).

## Backtest completo locale (2026-11-17, `make backtest` lanciato dall'utente, 71 min 36 s)

PUN ufficiale GME + stima 7 zone, meteo 7 città, gas TTF; 26 emissioni orarie, 24 giornaliere. Da `data/backtest-local.json`.

| Modello orario | MAE 1° g | MAE 7 gg | MAE 30 gg | Copertura 90% |
|---|---|---|---|---|
| naive-week | 18,6 | 20,8 | 25,9 | 0,80 |
| timestral-28m | 14,0 | 16,7 | 23,5 | 0,90 |
| timestral-209m | 12,8 | 15,7 | 22,7 | 0,90 |
| timestral-28m+meteo | 13,8 | 15,3 | 22,7 | 0,90 |
| timestral-28m+gas | 13,7 | 16,6 | 23,5 | 0,90 |
| timestral-28m+meteo+gas | 13,7 | 15,3 | 22,7 | 0,90 |
| **timestral-209m+meteo** (scelto) | **12,3** | **14,0** | 22,8 | 0,90 |

Giornaliero 3 mesi: **timestral-28m** (scelto) MAE 90 gg 20,7 contro profilo stagionale 23,0 e media 28 giorni 26,0. Il backtest rapido locale aveva scelto il profilo stagionale: con quello completo il modello giornaliero locale coincide con quello pubblico. Il gas resta senza effetto misurabile sopra il meteo.

Note: nota la baseline `mean-4w` aveva un bug nella banda (corretto il 2026-11-17 dopo questi numeri: la sua copertura è da rimisurare). Il periodo include il salto di regime 2025–2026 (media mensile da ~107 a ~249 €/MWh).
