# AFONDO

**Go deeper. Know better.**

AFONDO è un progetto di analisi delle notizie orientato alle prove: articoli, affermazioni, fonti originali e verifiche tracciabili.

Questa repository contiene la base del motore **AFONDO Check**, non un fact-checker completo. Nessun punteggio è prodotto senza evidenze esaminate. La prima implementazione usa estrazione euristica di frasi candidate, revisioni esplicite delle prove e uno score *sperimentale* limitato alle affermazioni.

## Pannello di amministrazione

AFONDO include un pannello riservato disponibile su **[http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin)**, con gestione delle fonti, delle autorizzazioni e dei provider AI (OpenAI, Anthropic, Gemini). Le chiavi vengono cifrate con Fernet nel database e non sono mai ritornate dal backend.

**Per entrare servono due variabili d'ambiente**, `AFONDO_ADMIN_TOKEN` e `AFONDO_ENCRYPTION_KEY`. Leggi le istruzioni passo passo in **[docs/ADMIN.md](docs/ADMIN.md)** prima di usare il pannello. Non pubblicare il pannello su Internet senza ulteriori protezioni. Nessuna scansione parte automaticamente; la verifica AI non è ancora collegata al provider.

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
- Preview dell'estensione Chrome con permesso `activeTab` (vedi `extension/README.md`)

## Registro fonti e metadata discovery

Il catalogo di 20 sorgenti è integrato nel backend. Apri [`/sources`](http://127.0.0.1:8000/sources) e [`/news`](http://127.0.0.1:8000/news) per i metadati individuati, oppure `GET /api/v1/sources` per visualizzare tipologia, metodo di discovery e stato del permesso. Le sorgenti includono RaiNews, DW, BBC, Euronews, France 24, Agência Brasil, Al Jazeera, Il Post, ANSA, AP, Reuters, Guardian, Africanews, NHK, The Conversation, ISTAT, Eurostat, NASA/JPL, UN News e Pagella Politica.

**Nessuna sorgente viene scaricata per impostazione predefinita.** Il registry non è una licenza. Solo dopo aver acquisito permessi espliciti, si configura un grant separato e si attiva manualmente `POST /api/v1/sources/{id}/sync` con token amministrativo: vedi [`docs/INGESTION.md`](docs/INGESTION.md).

Il comando `python -m afondo.sync_sources --dry-run` elenca le fonti senza accedere alla rete; `--once` avvia una singola sincronizzazione solo per quelle esplicitamente autorizzate. Per il setup consultare `docs/INGESTION.md`.

I connettori RSS/Atom/RDF e JSON configurabile salvano esclusivamente titolo, URL e data di pubblicazione. Per API proprietarie servono endpoint, contratto e integrazioni specifiche. È una pipeline di scoperta, non scraping di articoli completi.

## Limitazioni intenzionali

Non esegue crawling di pagine HTML o acquisizione di articoli integrali; il modulo discovery opzionale registra solo metadati da feed/API autorizzati. Non traduce automaticamente, non verifica in autonomia le affermazioni, non attribuisce punteggi a persone o testate. Queste funzioni richiedono fonti lecite, validazione del metodo, gestione dei diritti e controlli più solidi.

Leggi `docs/METHODOLOGY.md`, `docs/ROADMAP.md` e [`docs/SOURCES.md`](docs/SOURCES.md). Il catalogo di 20 fonti candidate è in [`config/source_candidates.json`](config/source_candidates.json): ogni scansione automatica resta disabilitata finché i permessi non sono verificati.

## Estensione Chrome (sviluppo locale)

Dopo aver avviato il backend, apri `chrome://extensions`, abilita la modalità sviluppatore, scegli **Carica estensione non pacchettizzata** e seleziona la cartella `extension/`. Apri un articolo, clicca sull'icona AFONDO e su **Analizza questa pagina**. Il testo visibile viene inviato al server locale solo su richiesta e l'estensione apre la scheda corrispondente nella dashboard.

## Esempi API

```bash
curl -s http://127.0.0.1:8000/health
# Specifica il JSON con titolo e testo di almeno 60 caratteri:
curl -s -X POST http://127.0.0.1:8000/api/v1/articles \\
  -H 'Content-Type: application/json' \\
  -d '{"title":"Notizia di esempio","text":"Prima affermazione da approfondire con prove pertinenti e controllate. Seconda affermazione sufficientemente lunga da analizzare separatamente."}'
```

Le prove inviate a `POST /api/v1/claims/{claim_id}/evidence` restano `pending`. Il revisore, dopo aver verificato l'evidenza, può usare `POST /api/v1/evidence/{evidence_id}/review` con intestazione `X-Review-Token`; consulta `/docs` per tutti gli schemi. La revisione non è esposta nella UI di questa demo.

## Docker

```bash
docker compose up --build
```

La demo è disponibile sulla porta 8000.

## Licenza

Nessuna licenza open source è stata ancora scelta. Il codice resta soggetto ai diritti del titolare finché non viene aggiunta una licenza.
