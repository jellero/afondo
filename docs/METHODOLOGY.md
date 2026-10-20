# AFONDO Check — metodo sperimentale v0.1

## Finalità

Il prodotto serve a collegare *affermazioni* a *prove tracciabili*. Non misura la verità in senso assoluto; non produce una classifica di giornalisti, testate o politici.

## Stato attuale del software

1. L'utente immette titolo, testo e, facoltativamente, metadati e URL originale.
2. Un algoritmo euristico identifica frasi candidate (minimo 30, massimo 600 caratteri).
3. Il sistema registra prove con URL, posizione (supports/refutes/unclear), tipologia (primary/secondary) e gruppo di provenienza indipendente.
4. Le prove restano **pending** finché un revisore autorizzato non le accetta o rifiuta.
5. Il sistema determina lo stato dell'affermazione usando **solo prove accettate**.
6. Calcola una metrica parziale solo con un campione minimo di affermazioni risolte.

## Regole esatte per una singola affermazione

- `supported`: almeno una prova accettata di fonte primaria o due gruppi di fonti secondarie indipendenti; nessuna prova accettata contraria.
- `refuted`: stessa regola per prove contrarie.
- `disputed`: coesistenza di prove accettate in entrambe le direzioni, senza decidere un vincitore.
- `insufficient_evidence`: condizioni precedenti non soddisfatte.

Il sistema **non autentica autonomamente** il carattere primario di una prova: il revisore è responsabile di verificare che documento, URL, classificazione e relazione con l'affermazione siano appropriati.

Le copie della stessa agenzia devono avere lo stesso `source_group`, altrimenti il contatore di indipendenza risulta falsato. Due gruppi non sono di per sé prova di verità: si tratta solo di una soglia euristica per il prototipo.

## Metrica articolo

`experimental_claim_support_ratio` = 100 × affermazioni `supported` / (`supported` + `refuted`).

Si calcola **solo se** almeno due affermazioni sono risolte e almeno il 60% delle candidate è risolto. Altrimenti il risultato è `null` e lo stato è `insufficient_evidence`. Le affermazioni `disputed` non entrano nel denominatore.

**NON è un punteggio globale di affidabilità dell'articolo.** Non misura completezza delle prove, correttezza del titolo, omissioni, distorsioni narrative, né fiducia nell'autore. Non consente confronti equi fra articoli di genere e complessità differenti.

## Cosa NON è ancora implementato

- [Parziale] Estrazione AI strutturata di affermazioni fattuali/opinioni/previsioni con citazioni esatte; da validare su un corpus editoriale e da integrare con un confronto indipendente delle prove
- Recupero autonomo delle fonti, fact-check esterno o traduzioni
- Analisi del contesto storico, temporale e statistico
- Verifica di citazioni tagliate e corrispondenza titolo/testo
- Verifica dell'indipendenza delle fonti e classificazione delle prove
- Calibrazione con revisori multipli o intervalli d'incertezza
- Storico per autore/testata e rettifiche
- Audit trail immutabile e processo di contestazione
- Protezioni adeguate per un deployment Internet pubblico

## Requisiti prima di una valutazione pubblica

- Dataset di riferimento etichettato da revisori diversi, con disaccordi misurati
- Risultati per lingua, tema e tipologia di articolo
- Test per allucinazioni, manipolazioni, falsi positivi e avvelenamento delle fonti
- Gestione dell'incertezza, versionamento del modello e riferimenti precisi alle prove
- Revisione legale su diritti di riproduzione, protezione dei dati e informazioni lesive
- Audit log di chi ha accettato ogni prova, autenticazione e autorizzazione robusta

## Principio fondamentale

**Un punteggio assente è migliore di un punteggio indimostrabile.**
