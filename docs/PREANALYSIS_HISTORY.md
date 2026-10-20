# AFONDO — Preanalisi automatica e storico di testate/autori

## Che cosa è stato implementato

1. Una **coda per la preanalisi AI dei testi già presenti nel database**.
2. Un **worker opzionale** per elaborare ripetutamente la coda, prima che il lettore consulti l'articolo.
3. Una ricerca di **piste documentali pertinenti** nei soli metadati già acquisiti con autorizzazione specifica.
4. Uno **storico pubblico di testate e firme** con gli articoli pubblicati, le segnalazioni documentate, le prove accettate e le revisioni editoriali.
5. Controlli amministrativi separati per permesso di invio all'AI, provenienza della notizia e verifica della firma.

L'implementazione non è ancora un verificatore completo: la sola corrispondenza tra titoli e affermazioni **non dimostra la verità dei fatti**. È intenzionalmente impossibile convertire automaticamente una pista documentale in una prova accettata o in un giudizio sulla testata.

## Pipeline: come preparare gli articoli prima della lettura

### 1. Materiale e diritti

Un articolo deve essere già presente in `articles`, con testo ottenuto lecitamente per il trattamento con un provider esterno. **Una voce RSS che contiene soltanto titolo e URL non è un testo autorizzato a un'analisi integrale** e non entra nella coda. Non sono previsti crawler HTML, download di contenuti completi né aggiramento di paywall.

Da `/admin` → **Preanalisi e storico** → seleziona l'articolo, registra:
- autorizzazione esplicita per l'invio del testo a un provider AI;
- riferimento verificabile e responsabile della verifica;
- scadenza del permesso, se applicabile.

Il permesso è revocabile. Sia l'estrazione manuale da `/admin` → Analisi AI sia quella automatizzata controllano il grant.

### 2. Elaborazione AI

Usa il provider selezionato nella sezione Intelligenza artificiale e il motore `ai_extraction.py` già presente. Gli estratti sono JSON strutturati con quote verbatim e offset; il sistema rifiuta citazioni non ancorate al testo originale. Ogni run è registrato con timestamp, modello, impronta del documento e contatori dei token forniti dal provider.

La preanalisi produce **candidate in attesa di revisione**. Non le pubblica come fatti accertati. Le candidate fattuali approvate passano al normale registro delle affermazioni; il giudizio rimane `insufficient_evidence` finché non ci sono prove esaminate.

### 3. Piste documentali

Se una fonte autorizza esplicitamente l'uso interno dei suoi metadati per trovare documenti pertinenti (`internal_evidence_lookup`), la pipeline confronta il testo delle candidate con i titoli già indicizzati, senza eseguire ulteriori download. I risultati vengono salvati come `ai_evidence_leads`: URL, fonte, termini corrispondenti e pertinenza lessicale approssimativa.

**Non vengono dichiarati prova, conferma o confutazione.** Un titolo può contenere parole simili per motivi diversi. Nessuna pista entra automaticamente nello scoring. Se il permesso di una fonte viene revocato, le piste associate cessano di essere mostrate dalla API di revisione.

Per attivare questa funzionalità, in `/admin` → Fonti registra, oltre alla metadata discovery, l'autorizzazione separata per la ricerca interna di documenti.

## Esecuzione una tantum

```bash
python -m afondo.preanalysis --dry-run
python -m afondo.preanalysis --once --limit 5
```

Il dry-run non invia alcun testo all'AI. L'esecuzione `--once` può consumare token del provider. Il pannello `/admin` → Preanalisi e storico offre anche il pulsante **Processa ora fino a 3 articoli**, sempre dietro conferma.

Il limite ereditato dal motore è di **25 richieste AI globali per 24 ore**, una per articolo ogni ora, massimo 12.000 caratteri di input per articolo e 12 candidate strutturate per estrazione. La coda processa soltanto articoli senza esecuzioni precedenti, evitando ripetizioni automatiche anche se una precedente chiamata è fallita. I retry richiedono un intervento amministrativo, dopo aver investigato la causa.

## Esecuzione periodica opzionale

Per evitare addebiti involontari, il worker periodico non fa parte dei servizi Docker avviati per default.

1. Completa `AFONDO_ADMIN_TOKEN` e `AFONDO_ENCRYPTION_KEY` nel file `.env` e configura un provider AI in `/admin`.
2. Registra permessi **per articolo** per l'uso del provider AI.
3. Aggiungi `AFONDO_ENABLE_PREANALYSIS=1` nel `.env`.
4. Esegui:

```bash
docker compose --profile automation up -d --build
docker compose logs -f preanalysis
```

Il servizio `preanalysis` controlla la coda ogni 900 secondi (15 minuti), processa al massimo 5 articoli per ciclo e applica sempre i limiti della pipeline. Configurare un intervallo maggiore tramite `AFONDO_PREANALYSIS_INTERVAL_SECONDS`, mai inferiore a 900.

Per disattivare il worker:

```bash
docker compose --profile automation stop preanalysis
```

**Importante:** si tratta di un processo locale avviato sul computer/server AFONDO, non di una funzione di ChatGPT che continua a operare autonomamente. In produzione è necessario un job worker affidabile, con code, retry, rate limit distribuiti e un budget monetario esplicito.

## Aggiornamento continuo dei feed autorizzati

AFONDO prevede un secondo worker indipendente, **solo per i metadati RSS/API** e
solo per le fonti con `metadata_discovery` documentata. Non scarica gli
articoli integrali e non li trasferisce al modello AI. Per abilitarlo, aggiungi
al file `.env`:

```dotenv
AFONDO_ENABLE_SOURCE_SYNC=1
AFONDO_SOURCE_SYNC_INTERVAL_SECONDS=3600
```

Poi esegui:

```bash
docker compose --profile source-automation up -d --build
docker compose logs -f source-sync
```

Le scansioni avvengono, al massimo, una volta all'ora, rispettando anche i
cooldown per provider, URL HTTPS approvati e permessi di ciascuna testata.
Per interromperlo:
`docker compose --profile source-automation stop source-sync`.

**La pipeline è divisa in due**: il worker RSS aggiorna soltanto l'elenco
delle notizie; il worker AI preanalizza soltanto articoli completi inseriti
legalmente nel database e autorizzati uno per uno per l'uso AI. **Non esiste
ancora un collegamento automatico dai titoli del feed al testo integrale
dell'articolo.** Questo richiederà accordi per il full text e connettori
dedicati conformi alle condizioni dei fornitori.

## Storico di testate e autori

La pagina pubblica `/history` e le API `/api/v1/history` permettono di esplorare i dossier storici.

Sono inclusi esclusivamente gli articoli:
- approvati editorialmente per la pubblicazione;
- dotati di nome testata e URL HTTPS originale;
- con attribuzione alla testata **confermata manualmente** in `/admin` → Preanalisi e storico.

Lo storico della **firma** richiede inoltre che un revisore abbia verificato il byline nell'articolo originale. Identità di testata = nome normalizzato più dominio della fonte; identità della firma = nome normalizzato più identità testata. Una firma su due testate differenti **non viene unita automaticamente**. Neppure ciò dimostra in modo univoco l'identità personale: per un sistema reputazionale servirebbero profili autore con identificativi affidabili, disambiguazione e contestazioni.

Ogni profilo mostra:
- nome, dominio e numero di articoli catalogati;
- numero di articoli associati a prove revisionate;
- numero di segnalazioni editoriali sui titoli e sul contesto;
- revisioni documentate e collegamenti alle fonti originali;
- per ogni articolo: eventuale nota editoriale, documenti e cronologia pubblica.

Questi **non sono voti** di attendibilità. Un campione sotto 10 articoli viene segnalato come limitato; anche sopra tale soglia si pubblicano soltanto quantità descrittive, non percentuali reputazionali. Gli articoli fuori dal catalogo, i generi opinione e gli eventi non verificati rendono qualsiasi classifica semplicistica potenzialmente fuorviante.

### Registro delle rettifiche

Le modifiche a una revisione editoriale pubblicata vengono registrate in `editorial_review_events`. Per cambiare note, segnalazioni o riferimenti di una scheda già pubblicata occorre una motivazione (almeno 15 caratteri) tramite `change_reason`. È possibile riportare la scheda in bozza, facendola scomparire dal feed e dallo storico pubblico. Gli eventi registrati rimangono nel database per audit interno, soggetti a politiche di conservazione.

## API aggiunte

| Endpoint | Accesso | Scopo |
|---|---|---|
| `GET /api/v1/admin/preanalysis` | Admin | Permessi e coda |
| `PUT /api/v1/admin/articles/{id}/processing` | Admin | Concedi/revoca il diritto di AI processing |
| `POST /api/v1/admin/preanalysis/once` | Admin | Una esecuzione esplicita del batch |
| `GET /api/v1/admin/attributions` | Admin | Stato delle attribuzioni |
| `PUT /api/v1/admin/articles/{id}/attribution` | Admin | Verifica testata e firma |
| `GET /api/v1/history?kind=outlet` | Pubblico | Elenco testate con dati verificati |
| `GET /api/v1/history?kind=author` | Pubblico | Elenco delle firme verificate |
| `GET /api/v1/history/{kind}/{id}` | Pubblico | Dossier, articoli e correzioni |

## Rischi ancora da risolvere prima del lancio

- **Ricerca di fonti originali per le affermazioni:** questa versione suggerisce documenti tramite parole nel titolo, ma non legge e verifica automaticamente documenti o statistiche.
- **Valutazione del contesto:** rimane editoriale, non automatizzata. Nessun modello attribuisce da solo l'etichetta sensazionalistica.
- **Storico di persone:** serve identificazione robusta dell'autore oltre alla firma, diritto di rettifica e replica, base GDPR e controllo della rappresentatività.
- **Storicizzazione delle prove:** snapshot/versioni dei documenti, motivazione della revisione e audit nominativo del revisore prima di scalare.
- **Produzione:** PostgreSQL + migrations, code di lavoro distribuite, RBAC/MFA, cifratura e backup, policy retention, osservabilità e review con più persone.

## Test

```bash
python -m pip install -e '.[dev]'
ruff check src tests
pytest -q
```

Sono inclusi test offline per permessi negati o scaduti, batch idempotente, finti output AI, attribuzioni verificate, storico, revisioni e revoche delle piste documentali. Non sostituiscono una prova dal vivo con le tue credenziali e fonti licenziate.
