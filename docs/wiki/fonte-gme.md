# Fonte: GME (Gestore dei Mercati Energetici)

Collegate: [Flussi dati](decisioni-flussi-dati.md), [Gas](fonte-gas.md).

## Termini
- **2026-11-17** — Termini del sito (https://www.mercatoelettrico.org/en-us/Home/TermsOfUse/): uso personale non commerciale consentito con citazione della fonte; vietata ridistribuzione; §6-bis vieta "crawlers, bots, scrapers or other automated tools, for any purpose whatsoever" e la "automated analysis" (eccezione: organismi di ricerca).
- **2026-11-17** — API GME: gratuita, anche per persone fisiche (modulo + documento), licenza per uso personale informativo, query automatiche entro quota. L'utente ha deciso di non usarla.
- Quindi: nessun download automatico da GME. I file li scarica l'utente a mano.

## Formato (campioni dell'utente, 2026-11-17)
- Zip `MGP_Prezzi<da><a>.zip` con `YYYYMMDDMGPPrezzi.xml` (orario, colonne Data, Mercato, Ora 1–24, PUN, NAT, zone…) e `…MGPPrezzi15.xml` (15 minuti, Periodo 1–96). Decimali con la virgola.
- La colonna **PUN** è il PUN Index GME (regola tecnica n. 25: media dei prezzi zonali pesata sulla domanda accettata); la media dei 4 quarti d'ora coincide con il valore orario.
- La colonna **NAT** differisce dal PUN (2–20 €/MWh nei giorni osservati): significato non chiarito, ignorata.
- `MGPGAS_SintesiScambio` (XML): prodotti gas MGP-giorno, WD (settimana), WE (weekend); il `PrezzoControllo` del prodotto D+1 esiste anche senza scambi → indicatore PSV giornaliero.
- `MGP_StimeFabbisogno`: domanda stimata per zona a 15 minuti; da qui i pesi zonali (Nord 0,584, CSud 0,170, CNord 0,086, Sud 0,063, Sici 0,053, Sard 0,025, Cala 0,019).
- Il file `MI-A1_PrezziZonali.xlsx` è il mercato infragiornaliero, non l'MGP: scartato.
