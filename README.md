# AFONDO

**Go deeper. Know better.**

AFONDO è un progetto di analisi delle notizie orientato alle prove: articoli, affermazioni, fonti originali e verifiche tracciabili.

Questa repository contiene la base del motore **AFONDO Check**, non un fact-checker completo. Nessun punteggio è prodotto senza evidenze esaminate. La prima implementazione usa estrazione euristica di frasi candidate, revisioni esplicite delle prove e uno score *sperimentale* limitato alle affermazioni.

## Avvio locale

Richiede Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn afondo.main:app --reload
```

Apri http://127.0.0.1:8000 per la demo e http://127.0.0.1:8000/docs per l'API.

Per abilitare l'endpoint di revisione delle prove in ambiente **locale e protetto**:

```bash
export AFONDO_REVIEW_TOKEN='scegli-una-chiave-lunga-e-casuale'
```

Senza la variabile, l'endpoint di revisione resta disabilitato. Non esporre un ambiente pubblico senza autenticazione robusta, rate limiting e controlli di accesso.

## Cosa c'è

- Inserimento di testi forniti dall'utente, con URL di attribuzione opzionale
- Estrazione euristica delle frasi candidate alla verifica (non fact-checking)
- Registro delle prove con URL, categoria e fonte indipendente
- Revisione esplicita delle prove con endpoint protetto da token
- Valutazione deterministica delle affermazioni solo su prove accettate
- Stato **dati insufficienti** quando non è giustificato un punteggio
- Storico locale SQLite e test automatici

## Limitazioni intenzionali

Non esegue crawling di siti terzi, non traduce automaticamente, non verifica in autonomia le affermazioni, non attribuisce punteggi a persone o testate. Queste funzioni richiedono fonti lecite, validazione del metodo, gestione dei diritti e controlli più solidi.

Leggi `docs/METHODOLOGY.md` e `docs/ROADMAP.md`.

## Docker

```bash
docker compose up --build
```

La demo è disponibile sulla porta 8000.

## Licenza

Nessuna licenza open source è stata ancora scelta. Il codice resta soggetto ai diritti del titolare finché non viene aggiunta una licenza.
