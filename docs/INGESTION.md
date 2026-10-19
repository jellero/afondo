# AFONDO — integrazione fonti e discoverer

## Stato

20 sorgenti sono censite in `config/source_candidates.json` (testate, agenzie, istituzioni, fonti di fact-checking). Sono ora disponibili via `GET /api/v1/sources`. Il motore di discovery integra **RSS 2, Atom, RDF e JSON API a schema configurabile**; non è un sistema che aggira paywall o scarica automaticamente il full text.

Per impostazione predefinita **0 fonti sono attive**. Questo evita di confondere la disponibilità tecnica di un RSS/API con il consenso o titolo giuridico a usarlo per il nostro prodotto.

### Stato delle integrazioni

- Fonti con RSS specifico in catalogo: connettore feed tecnicamente pronto, ma bloccato fino alla registrazione del permesso.
- Fonti con *catalogo* di feed, senza URL di un RSS specifico validato: serve URL esatto nel grant.
- Fonti solo website: serve individuare un feed/API consentito, oppure accordo per link e metadati. Niente HTML scraping automatico come fallback.
- Reuters, AP, Guardian: API partner da configurare **dopo** aver ottenuto accesso e licenze. Il connettore JSON generico funziona per uno schema mappato, ma non implica che lo schema delle API proprietarie sia supportato senza adattamenti.

### Autorizzazione di una fonte (operatore)

1. Verifica il diritto di effettuare esattamente *metadata discovery* per il progetto AFONDO, comprese finalità commerciali e AI se pertinenti. Non è sufficiente che il feed si apra in un browser.
2. Conserva riferimenti verificabili (contratto/autorizzazione/termini in vigore) e data di verifica.
3. Copia `config/source_grants.example.json` in `config/source_grants.json` e crea una chiave con l'ID della fonte.
4. Inserisci un grant valido: `permission_recorded=true`, `allowed_uses=["metadata_discovery"]`, `permission_reference`, `approved_by`, `reviewed_on`, `approved_host` e facoltativamente `expires_on`.
   - **Docker Compose:** salva il grant in `data/source_grants.json` (già montato nel container). Per installazione Python locale usa il percorso `config/source_grants.json` oppure imposta `AFONDO_SOURCE_GRANTS`.\n5. Per fonti prive di feed puntuale, configura `endpoint` con URL HTTPS esatto e `adapter: "feed"` o `"json_api"`.
6. Aggiungi un segreto d'ambiente `AFONDO_INGEST_TOKEN` diverso dal token usato per la revisione delle prove. Non commettere grants, autorizzazioni riservate o chiavi API in Git.
7. Esegui `POST /api/v1/sources/{source_id}/sync` con `X-Ingest-Token`, oppure il comando CLI per tutte le fonti autorizzate. È un'azione esplicita: **non esiste uno scheduler automatico abilitato**.

#### CLI per tutte le fonti autorizzate

```bash
python -m afondo.sync_sources --dry-run
python -m afondo.sync_sources --once
python -m afondo.sync_sources --once --source dw-en
# con Docker Compose (se il container è attivo):
docker compose exec afondo python -m afondo.sync_sources --dry-run
```

`--dry-run` **non effettua richieste alle testate**. `--once` raggiunge soltanto gli endpoint di fonti con grant completo, rispettando il cooldown di 15 minuti. Per l'esecuzione periodica, configurare un job `cron`, systemd timer o scheduler esterno **solo dopo** l'approvazione dei permessi e della rete di egress. Per un uso continuativo aggiungere osservabilità e limitazione della concorrenza.

Il campo `approved_host` deve corrispondere **esattamente** all'hostname del feed/API finale. HTTPS porta 443, no redirect automatici; i redirect devono essere verificati e l'URL finale registrato esplicitamente. Usare anche policy egress sulla rete in produzione.

Esempio **illustrativo, non è una concessione effettiva**:

```json
{
  "sources": {
    "rainews-it": {
      "permission_recorded": true,
      "allowed_uses": ["metadata_discovery"],
      "permission_reference": "RIFERIMENTO_DOCUMENTATO_DA_OTTENERE",
      "approved_by": "Responsabile autorizzazioni",
      "reviewed_on": "2026-10-19",
      "approved_host": "www.rainews.it"
    }
  }
}
```

Non attivare l'esempio senza un titolo d'uso documentato.

### API

| Endpoint | Funzione | Permessi |
|---|---|---|
| `GET /api/v1/sources` | Tutte le fonti con stato ed eventuale storico sync | Pubblico locale |
| `GET /api/v1/sources/{id}` | Stato di una fonte | Pubblico locale |
| `GET /api/v1/discoveries?source_id=...` | Metadati rilevati, URL e pubblicazione | Pubblico locale |
| `POST /api/v1/sources/{id}/sync` | Discovery metadata esplicita | Token amministrativo e permessi documentati |
| `GET /sources` | Dashboard fonti | Pubblico locale |\n| `GET /news` | Metadati acquisiti e collegamenti alla fonte | Pubblico locale |

```bash
export AFONDO_INGEST_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
curl http://127.0.0.1:8000/api/v1/sources
curl -X POST http://127.0.0.1:8000/api/v1/sources/rainews-it/sync \
  -H "X-Ingest-Token: $AFONDO_INGEST_TOKEN"
curl 'http://127.0.0.1:8000/api/v1/discoveries?source_id=rainews-it'
```

Senza il grant, la richiesta `sync` torna HTTP 409; senza token abilitato torna HTTP 503. Il rate limiting per ciascuna fonte è di **almeno 15 minuti tra i tentativi**. La risposta ha un limite di 1,5 MB e il parser accetta massimo 100 item. Usa ETag / Last-Modified se forniti dal provider.

### API JSON partner generica

Una volta ottenuti endpoint e schema forniti dal provider, configura `adapter: "json_api"`, `endpoint`, `approved_host` e `api_schema`:

```json
{
  "api_schema": {
    "items_path": "response.results",
    "title_field": "webTitle",
    "url_field": "webUrl",
    "published_field": "webPublicationDate",
    "id_field": "id"
  },
  "token_env": "AFONDO_SOURCE_PARTNER_TOKEN",
  "token_header": "X-API-Key"
}
```

**Attenzione:** questa è una mappatura strutturale, non la certificazione di compatibilità con il modello di autenticazione o i termini del Guardian o di altri fornitori. Gestire separatamente query, paginazione e quote nel relativo adapter dopo aver ottenuto le specifiche autorizzate.

### Modello dei dati

I metadati persistono in `discovered_items` (`source_id`, `title`, `url`, `published_at`, `discovered_at`, `external_id`). La constraint `UNIQUE(source_id,url)` garantisce deduplica e import idempotente. `source_sync_state` registra ultimo tentativo, stato, elementi visti, errori, ETag e Last-Modified.

Nessun articolo completo viene scaricato o inviato all'AI. La lettura AI richiederà in seguito un grant distinto: **`fulltext_ai_analysis`**, attualmente non supportato da questa pipeline.

### Hardening prima del deployment pubblico

- Migrazioni DB, PostgreSQL, tracciabilità di chi ha approvato una fonte, revoche, rinnovi di permessi e controllo delle scadenze.
- Auth JWT/OIDC + RBAC; rate limit globale, distributed locks, coda di processi e audit log.
- HTTP client resistente a DNS rebinding e outbound proxy con allowlist/pinning IP.
- Conformità alle condizioni aggiornate, robots, quote, versionamento dei diritti e data retention.
- Rilevazione automatiche di duplicati *tra* domini/eventi e di articoli derivati dalla stessa agenzia.
- Pipeline eventi, parsing robusto di date/metadati e preservazione della lingua originale.
