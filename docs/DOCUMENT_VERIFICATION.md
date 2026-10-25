# AFONDO — Verifica documentale e controllo del contesto

## Scopo

Il passaggio **dalla preanalisi AI a una verifica fondata su documenti** ora
dispone di una coda operativa. Non dichiara che un articolo sia falso soltanto
perché due testi contengono numeri differenti: ogni riscontro deve passare dalla
verifica dell'originale e da una valutazione del significato dei dati.

Questa è una prima versione, **non ancora un motore di fact-checking autonomo
con ricerca e lettura universale del web**. Non recupera siti arbitrari, non
bypassa paywall, non conclude automaticamente il confronto semantico.

## Workflow

1. **Acquisizione legittima** — il contenuto di un articolo viene registrato
   con i permessi appropriati. Il worker AI opzionale estrae affermazioni
   fattuali e le mette in coda.
2. **Documento originale** — in `/admin` → **Documenti e contesto**, l'operatore
   registra l'URL HTTPS, editore o ente, raggruppamento della fonte, data,
   posizione precisa (pagina / tabella / sezione) e un estratto limitato
   necessario alla verifica. È obbligatorio documentare il titolo per
   conservare e utilizzare l'estratto. **AFONDO non scarica automaticamente
   l'URL:** la persona deve aver consultato l'originale.
3. **Revisione separata** — un secondo revisore, diverso da chi ha inserito il
   documento (identificazione registrata per nome nella versione MVP), verifica
   l'originale. Solo dopo l'approvazione l'estratto può entrare negli
   abbinamenti.
4. **Abbinamento automatico** — il sistema confronta i termini delle candidate
   e i documenti già approvati. Applica un filtro di corrispondenza prudente
   per evitare milioni di accoppiamenti casuali, ma questa pertinenza è solo
   lessicale e può sbagliare.
5. **Segnali di contesto** — sono cercate esplicitamente differenze di anni,
   percentuali e altre quantità con unità compatibile tra frase e passaggio
   documentale. La dicitura è **«Da esaminare»**, non «Falso», «Menzogna» o
   «Fuori contesto».
6. **Decisione editoriale** — un revisore marca la pertinenza della coppia
   come rilevante o irrilevante e registra perché.
7. **Proposta di prova** — per una candidata fattuale già accettata, il
   revisore può proporre una prova a sostegno, contraria o non conclusiva,
   indicando la motivazione. La prova viene inserita in `evidence` con
   `review_status='pending'`, dunque **non cambia il punteggio**.
8. **Revisione delle prove** — una revisione distinta tramite
   `/api/v1/evidence/{id}/review` (con `AFONDO_REVIEW_TOKEN`) è obbligatoria
   perché la prova influisca sullo scoring. Lo storico di testate/autori
   continua a mostrare soltanto dati documentati e parziali.

Le candidate vengono abbinate sia quando termina un nuovo run AI, sia quando
viene approvato un nuovo documento. Le coppie già revisionate non vengono
sovrascritte da scansioni ripetute.

## Perché cifre differenti non significano «notizia falsa»

L'esempio «40% nel 2025» e «4% nel 2024» produce due avvisi: anni differenti
e percentuali differenti. Senza un controllo di metodologia, Paese, categoria
di prezzo, serie storica, periodo e popolazione, le due misure possono essere
entrambe corrette. Il sistema **non modifica automaticamente** lo stato
editoriale `sensationalistic` o `out_of_context` sulla homepage.

Il comparatore deterministico di questa versione:
- confronta anni scritti esplicitamente e quantità accompagnate da unità,
  gestendo virgola/punto decimali in modo semplice;
- **non** interpreta negazioni, unità implicite, definizioni statistiche,
  riferimenti temporali relativi, medie, percentili, margini d'errore,
  scale o trasformazioni complesse;
- non esegue traduzioni né query esterne;
- produce soltanto candidati da revisionare con motivazione spiegabile.

## Provenienza e revoca

Il documento è immutabile nel prototipo: viene creato come `submitted`,
può essere `approved`, `rejected` oppure `retired`; non è possibile
alterarne silenziosamente il testo dopo la verifica. Una riga di collegamento
`document_evidence_links` conserva il rapporto tra confronto, estratto e prova.

**Se un documento è ritirato**, i suoi confronti non vengono più restituiti
nell'area operativa, e le prove precedentemente accettate e collegate
cessano di contare nel calcolo delle affermazioni e degli aggregati storici.
Lo storico della decisione originale resta nel database per audit; l'API
dell'articolo distingue il precedente `stored_review_status` da quello
effettivo `review_status`.

Il sistema blocca anche nuovi tentativi di accettare una prova collegata a un
documento ritirato.

## API e persistenza

| API protetta da X-Admin-Token | Scopo |
|---|---|
| `POST /api/v1/admin/documents` | Registra estratto, permesso e provenienza |
| `GET /api/v1/admin/documents` | Elenca gli estratti |
| `POST /api/v1/admin/documents/{id}/review` | Approva, rifiuta o ritira |
| `GET /api/v1/admin/context-queue` | Confronti proposti e segnali espliciti |
| `POST /api/v1/admin/context-matches/{id}/decision` | Conferma o esclude la pertinenza |
| `POST /api/v1/admin/context-matches/{id}/evidence-proposal` | Crea una prova `pending` |

Nuove tabelle: `evidence_documents`, `document_claim_matches`,
`document_evidence_links`. Si aggiungono senza distruggere i dati esistenti
tramite `CREATE TABLE IF NOT EXISTS`. Restano da introdurre migrazioni
versionate e un archivio documenti completo prima della produzione.

## Sicurezza e limiti

- Nessuna richiesta HTTP a URL inseriti dagli utenti è eseguita da questo
  modulo. Gli URL sono riferimenti cliccabili, mai endpoint di download.
- L'estratto è massimo 4.500 caratteri, con posizione esatta e titolo.
  Non copiare materiale più ampio del necessario o senza titolo giuridico.
- La conferma dei due revisori è basata su due nomi dichiarati: senza utenti,
  RBAC, audit nominativo e MFA **non è una garanzia tecnica di separazione
  delle funzioni**. Il pannello resta destinato a uso locale controllato.
- Le corrispondenze sono solo suggerimenti; niente punteggi all'autore,
  niente etichette automatiche «fake news».
- L'assegnazione `source_kind='primary'` e il gruppo di indipendenza sono
  dichiarati dal revisore e richiedono controllo reale prima di accettare la
  prova.
- Le altre prove non collegate a documenti rimangono soggette al precedente
  percorso di revisione manuale.

## Test

```bash
python -m pip install -e '.[dev]'
ruff check src tests
pytest -q tests/test_context_workbench.py tests/test_scoring.py
```

I test sono offline: controllano cifre e anni, blocco dell'auto-approvazione,
inserimento delle prove solo come pending, divieto dei duplicati e ritiro di
documenti precedentemente utilizzati. Non eseguono una vera verifica editoriale
o il recupero online dei documenti.
