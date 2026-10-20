# AFONDO Control — pannello di amministrazione

Percorso locale: **http://127.0.0.1:8000/admin**

Il pannello consente di aggiungere, aggiornare e archiviare fonti; registrare autorizzazioni per la metadata discovery; configurare chiavi di provider AI (OpenAI, Anthropic, Gemini), conservarle cifrate e verificarne la raggiungibilità. Include stato delle fonti e ultima sincronizzazione.

**Le chiamate AI sono ora collegate all'estrazione di affermazioni su richiesta, ma non alla verifica autonoma tramite fonti esterne.** Nessuna fonte senza autorizzazione viene sottoposta a crawling.

## Configurazione una tantum

1. Installa le dipendenze con `pip install -e '.[dev]'` oppure con `docker compose build`.
2. Genera due valori diversi e segreti:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(40))'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

3. Crea un file `.env` nella cartella del progetto (è ignorato da Git):

```dotenv
AFONDO_ADMIN_TOKEN=INCOLLA_QUI_IL_TOKEN_LUNGO
AFONDO_ENCRYPTION_KEY=INCOLLA_QUI_LA_FERNET_KEY
# Opzionale per endpoint di sync già esistente:
AFONDO_INGEST_TOKEN=UN_ALTRO_TOKEN_LUNGO
```

4. Se usi Docker, `docker compose up --build` legge automaticamente `.env`. Se usi Python locale, esporta le variabili da `.env` nell'ambiente di shell con uno strumento adatto prima di avviare `uvicorn afondo.main:app --reload`; Uvicorn non legge automaticamente il file `.env`.
5. Apri `http://127.0.0.1:8000/admin` e inserisci `AFONDO_ADMIN_TOKEN`.

Nella UI, il token admin resta **solo in memoria Javascript** e viene cancellato con Esci o con il reload. Le credenziali AI vengono inviate solo sul server locale o tramite HTTPS e cifrate con **Fernet**; il database SQLite conserva solo il ciphertext. La master key deve restare fuori da Git e va mantenuta in un secret manager in produzione. **Se perdi la master key, non puoi decifrare le API key salvate.**

### Se usi Docker per generare la chiave

Dopo `docker compose build`, puoi eseguire:

```bash
docker compose run --rm afondo python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

## Funzioni

### Fonti

- Registrazione di nuove testate con nome, ID, categoria, sito HTTPS, lingue, aree geografiche e endpoint RSS.
- Modifica o archiviazione delle fonti; nessuna viene eliminata dai metadati storici.
- Sezione autorizzazioni: flag di autorizzazione, riferimento documentato, responsabile della verifica, data e scadenza, endpoint esatto, adapter (RSS o JSON API) e mapping API.
- Le fonti vengono disabilitate alla creazione. Solo un grant documentato valido e il flag **attivo** permettono la discovery.
- Se cambi sito/feed o metodo di acquisizione, viene invalidato il grant precedente per impedire che una vecchia autorizzazione si applichi a un endpoint differente.
- Le configurazioni sono in SQLite `admin_sources` e `admin_source_grants`; il catalogo JSON iniziale resta disponibile come base. I grant salvati nel database hanno precedenza su un grant JSON precedente, comprese le revoche.

**Attenzione:** il campo "Ho verificato un'autorizzazione" è una registrazione effettuata dall'operatore, non un'autorizzazione concessa da AFONDO o dal fornitore. Verificare sempre diritti, condizioni, quote e riserve per AI/TDM.

Le API per la sync delle fonti continuano a richiedere `AFONDO_INGEST_TOKEN` indipendentemente da `AFONDO_ADMIN_TOKEN`. Non è presente un pulsante nel pannello per lanciare indiscriminatamente tutte le scansioni.

### AI

- Configurazione del provider (OpenAI / Anthropic / Gemini) e modello tramite **ID effettivo**.
- API key nuova o sostituzione della precedente; lasciare il campo vuoto durante la modifica la conserva senza mostrarla.
- Impostazione di un provider predefinito, disattivazione, cancellazione definitiva della configurazione.
- Test autenticato server-side verso la lista modelli del provider; non invia articoli e non effettua inferenze.
- Gli endpoint di test sono *fissi* nel codice; il browser non fornisce URL e il backend non effettua redirect che potrebbero inoltrare chiavi a un'altra origine.

Il test di connessione **non dimostra** che il modello specifico supporti l'output strutturato. Per verificare la reale compatibilità usa la scheda **Analisi AI** su un articolo che puoi lecitamente elaborare. Il fact-check tramite fonti esterne resta separato e non ancora automatizzato.

## Nuova sezione: Pubblicazione

Il pannello comprende **Pubblicazione** per impostare categoria, notizia
in evidenza e approvazione prima che un testo sia mostrato nel nuovo portale
`/`. Le segnalazioni “sensazionalistico” e “fuori contesto” sono visibili
esclusivamente dopo una revisione documentata con nota di almeno 40 caratteri
e URL HTTPS consultabile. Questi giudizi non vengono attribuiti dall'AI.

La sezione Fonti ora distingue il permesso di discovery RSS/API dal diritto
di **pubblicare titoli e metadati** nel portale: due concessioni diverse.
Le notizie non autorizzate non vengono mostrate.

Vedi [docs/PORTAL.md](PORTAL.md).

## Nuova sezione: Analisi AI

La scheda **Analisi AI** elenca gli articoli già registrati, esegue l'estrazione con il provider predefinito solo dopo conferma, mostra modello e consumo token e permette di accettare o rifiutare candidate. La verifica dei fatti resta separata.

- Limite 12.000 caratteri per articolo; articoli più lunghi vanno rielaborati con policy esplicite.
- Massimo 25 tentativi globali / 24 ore e 1 tentativo per articolo / ora.
- L'invio può comportare costi e trattamento esterno dei dati; non inviare contenuti senza autorizzazioni.
- Accettare una candidata `factual` la aggiunge al registro `claims`, senza attribuire alcuna verità.

Consulta [`docs/AI_EXTRACTION.md`](AI_EXTRACTION.md) per dettagli operativi e tecnici.

## API protette

Tutte le seguenti rotte richiedono `X-Admin-Token`:

| Endpoint | Funzione |
|---|---|
| `GET /api/v1/admin/status` | Stato del pannello |
| `GET /api/v1/admin/sources` | Fonti e autorizzazioni |
| `POST /api/v1/admin/sources` | Nuova fonte |
| `PUT /api/v1/admin/sources/{id}` | Modifica fonte |
| `DELETE /api/v1/admin/sources/{id}` | Archivia fonte |
| `PUT /api/v1/admin/sources/{id}/grant` | Registra/ritira autorizzazione |
| `GET /api/v1/admin/ai` | Configurazioni provider senza chiave |
| `PUT /api/v1/admin/ai` | Salva provider e chiave cifrata |
| `DELETE /api/v1/admin/ai/{provider}` | Elimina configurazione |
| `POST /api/v1/admin/ai/{provider}/test` | Test di sola connettività |

## Sicurezza e limitazioni

Questa implementazione è per **ambiente locale / sviluppo controllato**. Docker Compose espone la porta solo su `127.0.0.1:8000`. Il backend rifiuta i token admin su URL HTTP remoti. Prima di pubblicare il pannello su Internet servono autenticazione forte con utenti/RBAC, protezioni anti-brute-force, rate limiting, audit log, reverse proxy HTTPS con corretta propagazione dello schema, hardening della rete e del browser, gestione delle chiavi tramite secret manager, migrazioni DB e backup cifrati.

Non mettere le chiavi nel codice, nei link o in un issue GitHub. Non fornire chiavi al chatbot: inseriscile soltanto nell'installazione AFONDO che controlli.

## Test

```bash
pip install -e '.[dev]'
ruff check src tests
pytest -q
```

Le chiamate AI nei test sono simulate offline. La CI esegue gli stessi controlli; l'esito va verificato su GitHub Actions.
