# AFONDO — Estrazione AI delle affermazioni (prima versione)

## Obiettivo

L'area [`/admin`](http://127.0.0.1:8000/admin) ora dispone della sezione **Analisi AI**: scegli un articolo già presente nel database, confermi esplicitamente l'invio del testo al provider esterno, avvii l'estrazione e rivedi le affermazioni candidate.

La pipeline separa tre concetti:
1. **Estrazione semantica** — il modello identifica affermazioni fattuali, opinioni, previsioni o formulazioni ambigue, con citazioni verbatim ancorate al testo.
2. **Revisione editoriale** — un amministratore accetta o rifiuta ciascuna candidata. Solo quelle classificate `factual` possono entrare nel registro `claims`.
3. **Verifica delle prove** — rimane distinta. Un'affermazione candidata non è confermata, contestata o smentita finché non esistono prove esaminate nel motore di scoring.

**Non è ancora disponibile un fact-checker automatico completo.** L'AI non effettua autonomamente web search, consultazione di documenti o confronti indipendenti; le nuove candidate iniziano senza prove e senza un punteggio di verità.

## Collegamento dei provider

Da `/admin` → `Intelligenza artificiale`, inserisci la chiave API e il **vero ID** di un modello supportato da output strutturati. Il sistema supporta:

- **OpenAI** — API Responses `POST https://api.openai.com/v1/responses` con `text.format.type=json_schema`, `strict=true`, `store=false`.
- **Anthropic** — Messages API `POST https://api.anthropic.com/v1/messages` con `output_config.format.type=json_schema`.
- **Google Gemini** — `generateContent` su endpoint ufficiale, con `generationConfig.responseFormat.text.mimeType=APPLICATION_JSON` e relativo schema.

Solo il provider marcato come predefinito è utilizzato. Il test di connettività della schermata AI prova l'autenticazione verso l'elenco modelli ma **non** esegue l'estrazione né dimostra compatibilità del modello selezionato. Le funzionalità di output JSON strutturato dipendono dal modello e dai permessi effettivi dell'account.

Gli endpoint HTTPS sono fissati lato server; **le chiavi vengono decifrate esclusivamente in memoria durante la richiesta**. In database si conserva la chiave cifrata con Fernet e gli esiti della pipeline, mai la risposta raw del provider.

Documentazione dei formati (verificata nel 2026):
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://ai.google.dev/api/generate-content

## Costi e limiti

- Ogni richiesta è **esplicita**, con conferma in UI prima di inviare testo e consumare crediti API.
- Il testo non deve superare 12.000 caratteri. Non viene inviato un testo parziale nascosto: articoli più lunghi vengono respinti con HTTP 422.
- Il modello può restituire massimo 12 candidate e usa un budget di massimo 2.200 token di output.
- Rate limit interno: massimo **25 tentativi globali ogni 24 ore** e **1 tentativo per articolo ogni 60 minuti**. Sono contabilizzati anche i fallimenti per contenere abusi.
- Timeout provider 35 secondi, massimo 120 KB di risposta, nessun redirect verso domini differenti.
- Per ogni analisi si registrano provider, modello, versione prompt, timestamp, impronta SHA-256 del testo analizzato, numero di candidate accettabili, token comunicati dal provider (se disponibili) ed esito. I token non equivalgono automaticamente a una stima di costo.

Questi limiti si applicano al prototipo SQLite; prima della produzione occorrono quota per organizzazione/utente, budget monetario per provider, job asincroni, timeout/retry gestiti, logging senza PII, audit e isolamento dell'egress.

## Qualità e provenienza

Le citazioni devono essere sottostringhe *identiche* del testo originale, con `start_offset` e `end_offset` calcolati dal server. Se un modello parafrasa un brano spacciandolo per citazione esatta, AFONDO lo scarta. Nessuna evidenza esterna viene inventata dal modello.

Si conservano i run e il loro esito separatamente dalle candidate. Un revisore può promuovere una candidata fattuale al registro delle affermazioni da verificare. Una candidata accettata **non ha automaticamente una valutazione**; la verifica richiede prove documentali e la relativa revisione.

Le candidate sono associate al testo originale e al run che le ha generate; se il testo non corrisponde più alla citazione, l'accettazione viene rifiutata.

## API amministrative

| API | Azione |
|---|---|
| `GET /api/v1/admin/article-queue` | Articoli disponibili per analisi |
| `GET /api/v1/admin/articles/{id}/ai` | Storico run e ultime candidate |
| `POST /api/v1/admin/articles/{id}/ai-extract` | Esegue una estrazione con modello selezionato |
| `POST /api/v1/admin/ai-candidates/{id}/decision?decision=accept` | Promuove una candidata fattuale alle verifiche |
| `POST /api/v1/admin/ai-candidates/{id}/decision?decision=reject` | Scarta una candidata |

Tutte le API richiedono `X-Admin-Token`. L'operazione non attiva alcuna scansione delle fonti: l'articolo deve essere già disponibile nel database.

## Esempio di flusso

1. Vai sul portale `/` e registra un testo che hai il diritto di elaborare, oppure usa l'estensione Chrome su richiesta.
2. In `/admin` configura un provider AI con chiave e modello; testa la connessione se necessario.
3. Vai su `Analisi AI`, scegli l'articolo e conferma l'estrazione.
4. Esamina ciascuna frase. Accetta soltanto candidate fattuali pertinenti.
5. Consulta l'articolo originale e aggiungi fonti probatorie attraverso gli endpoint `/api/v1/claims/.../evidence`; verifica manualmente la prova prima di approvarla.
6. Finché non esistono prove accettate, AFONDO mantiene la classificazione **insufficient_evidence**.

## Privacy e diritti

**L'invio a un provider AI esterno è un trattamento distinto dalla raccolta o consultazione di un articolo.** Prima di fare l'invio verifica la licenza dell'articolo, le riserve AI/TDM, il trattamento dei dati personali, eventuali informazioni riservate e le condizioni del provider. Non inviare documenti protetti o riservati senza titolo e basi adeguati.

Il modello non determina automaticamente l'affidabilità di un giornalista o di una testata.

## Test

```bash
python -m pip install -e '.[dev]'
ruff check src tests
pytest -q
```

`tests/test_ai_workflow.py` contiene fixture offline e sostituisce le chiamate HTTP ai modelli; nessuna API key reale è necessaria per la suite. La compatibilità live con uno specifico model ID resta da testare nell'ambiente dell'operatore.
