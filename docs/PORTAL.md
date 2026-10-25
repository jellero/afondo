# AFONDO — Portale notizie e segnali immediati

## Obiettivo dell'interfaccia

La home `/` è il **portale di lettura**, non più il modulo di inserimento testi.
Mostra un flusso di notizie ordinato, con un indicatore di stato visibile già nella
card, categorie, ricerca, prima pagina e pannello di dettaglio. Il modulo di
inserimento e la preview dell'estensione restano disponibili su `/analyze`.

**Il portale non avvia inferenze AI quando un lettore apre una pagina o clicca su una
notizia.** Usa i dati che AFONDO ha già acquisito, le revisioni salvate e la
valutazione delle affermazioni con prove esaminate. In mancanza di dati la UI
mostra uno stato neutro, non una finta classificazione.

## Esperienza utente

- **Notizie** — card leggibili con titolo, testata, categoria, data e pallino colorato.
- **Categorie** — Tutte, Attualità, Politica, Economia, Mondo, Tecnologia,
  Scienza, Salute, Ambiente, Sport e Cultura.
- **Recenti** — prima le notizie in evidenza approvate, poi quelle più recenti.
- **In tendenza** — proxy *copertura multi-testata*: almeno due diverse
  fonti registrate con titoli quasi identici negli ultimi tre giorni. NON indica
  dati di traffico, ricerche, lettori o conferme indipendenti.
- **Analizzate** — card con almeno un segnale probatorio basato su evidenze
  accettate o una revisione editoriale motivata.
- **Dettaglio** — pannello laterale con significato dell'indicatore,
  motivazione, eventuale documento a sostegno e link al sito originale.
- **Mobile** — layout a colonna, scorrimento orizzontale delle categorie,
  schede compatte, tipografia e contrasti accessibili. Per tastiera,
  è possibile premere `/` per mettere a fuoco la ricerca.

## I colori non sono un giudizio assoluto

| Colore | Stato | Condizione |
|---|---|---|
| Grigio | Non ancora verificata | Solo metadata o prove non sufficienti |
| Verde | Affermazioni supportate | Almeno due affermazioni risolte; copertura minima del 60%; nessuna smentita tra quelle risolte |
| Rosso | Affermazioni contestate | Riscontro di affermazioni confutate in una valutazione provvisoria con prove accettate |
| Ambra | Titolo sensazionalistico e/o fuori contesto | Esclusivamente dopo la pubblicazione di una revisione editoriale motivata e corredata da un URL consultabile |

Se coesistono più segnali, il dettaglio elenca tutti quelli riconosciuti.
I colori non misurano la qualità complessiva del giornalista o della testata.

La classificazione dei **temi** usa ancora parole chiave del titolo (provvisoria,
non una tassonomia AI validata); l'operatore può correggere una categoria nel pannello.

## Regole di pubblicazione

**Due percorsi distinti:**

1. **Articolo con testo in AFONDO** (portale `/analyze`, estensione, futura
   importazione autorizzata). Per evitare spam, contenuti caricati da terzi e
   giudizi prematuri, compare sul portale pubblico **solo se un amministratore
   imposta una revisione editoriale `approved`**. La revisione può essere
   approvata anche senza un verdetto (in tal caso compare “Non ancora
   verificata”). L'opzione `featured` permette di metterlo in primo piano.
2. **Notizia da feed RSS o API**. Si mostra soltanto titolo, URL, fonte, data e
   categoria stimata; lo stato è sempre **non verificata** senza il testo e la
   documentazione. Occorrono sia la registrazione del permesso
   `metadata_discovery` sia `public_metadata_display`; se la concessione
   viene revocata o scade, i metadati già acquisiti non vengono più mostrati
   sul portale. La registrazione di un feed non costituisce automaticamente una
   concessione del diritto alla pubblicazione.

**Le segnalazioni qualitative sensibili** (“sensazionalistico”, “fuori contesto”)
sono operazioni redazionali. Sono visibili solo se `approved`, corredate da una
motivazione di minimo 40 caratteri e da un URL HTTPS. L'operatore deve consultare
effettivamente la fonte originale e accertare la pertinenza del riferimento; la
presenza di un URL non basta per dimostrare la valutazione.

## Come si gestisce

1. Dal pannello `/admin` → **Pubblicazione**, scegli un articolo già registrato.
2. Seleziona la categoria oppure lascia la categorizzazione provvisoria del titolo.
3. Seleziona **Approvata** per renderlo visibile.
4. Opzionalmente: seleziona **In primo piano**.
5. Se c'è un problema di titolo o contesto, spunta l'avviso, aggiungi motivazione
   e URL a supporto e pubblica. La scheda pubblica mostrerà indicatore e
   documentazione. Per ritirarlo rimetti lo stato in **Bozza**.

Per pubblicare i titoli dei feed, in `/admin` → **Fonti** registra separatamente
la base per l'acquisizione dei metadati e la licenza di visualizzazione pubblica.
I feed senza grant valido non vengono mostrati.

## API

`GET /api/v1/feed?topic=economia&sort=recenti&q=energia&limit=48`

I parametri `topic` e `sort` consentono filtri per categoria,
`recenti`, `tendenza` e `verificate`. Ogni item include `indicator`
(`state`, `label`, `flags`, `reviewed`, `note`, `evidence_url`),
`coverage_sources`, `topic`, `source`, `url`. **Il corpo completo
dell'articolo non viene incluso nel feed pubblico.**

`GET /api/v1/admin/editorial` e `PUT /api/v1/admin/editorial/{article_id}`
sono protette con `X-Admin-Token`.

## Storico e preanalisi autorizzata

Il nuovo percorso [`/history`](http://127.0.0.1:8000/history) raccoglie
pubblicazioni attribuite manualmente a una testata e, quando confermata,
alla firma riportata dall'articolo. Mostra cronologie delle segnalazioni e
delle rettifiche, non un voto personale. Per visibilità servono sia l'approvazione
editoriale sia la verifica di provenienza.

Il sistema include inoltre una **coda opzionale di preanalisi AI** che opera sui
soli testi per cui è stato verificato il diritto di inviarli al provider. Le
proposte di documenti dell'indice sono soltanto piste da verificare. Non è ancora
disponibile una valutazione automatica dei documenti probatori.

Vedi [PREANALYSIS_HISTORY.md](PREANALYSIS_HISTORY.md).

## Cosa aggiunge il confronto documentale

Nel pannello `/admin` → Documenti e contesto il revisore può indicizzare
brevi estratti di fonti ufficiali, verificarne l'origine e prepararne il
confronto con le affermazioni. La prima versione rileva differenze
esplicite tra percentuali e anni, senza inferire che un articolo sia
falso o fuori contesto.

La revisione documentale e la registrazione della prova sono separate
dalle segnalazioni colorate del portale. Le prove collegate a documenti
poi ritirati cessano di contribuire al conteggio dell'evidenza.
Vedi [DOCUMENT_VERIFICATION.md](DOCUMENT_VERIFICATION.md).

## Limiti della versione attuale

- Il feed non è ancora alimentato da testate autorizzate in produzione.
- Il raggruppamento delle tendenze si basa su un confronto prudente dei titoli
  recenti, non su un sistema industriale di clustering per evento. Titoli diversi
  dello stesso evento potrebbero non essere collegati; titoli simili potrebbero
  creare falsi accorpamenti.
- Nessuna traduzione automatica IT/EN, nessuna ricerca web autonoma delle prove,
  nessun riconoscimento AI affidabile di omissioni o sensazionalismo.
- Il voto di affidabilità complessiva ad autori e testate non è implementato.
- In produzione saranno necessari autenticazione di più revisori, doppia firma
  per segnalazioni reputazionali, procedure di rettifica, calibrazione delle
  verifiche, audit delle revisioni, moderazione, cache/CDN, scheduler e test
  completi di sicurezza/accessibilità.

La coda di preanalisi AI è stata aggiunta come worker opzionale: per la
versione successiva rimangono da sviluppare il recupero lecito dei documenti
originali, il confronto dei fatti, l'analisi automatica del contesto e la
validazione editoriale dei casi controversi. Non trasformare il giudizio di un LLM in un'etichetta pubblica
senza una catena di prove verificabili.
