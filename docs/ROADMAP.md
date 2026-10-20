# AFONDO — piano tecnico

## Milestone 0 — Fondazioni (in questa repository)

- [x] FastAPI con API OpenAPI
- [x] Persistenza SQLite semplice
- [x] Articoli + candidate claims + evidence
- [x] Revisione delle prove protetta da token per uso locale
- [x] Metrica sperimentale con astensione su dati insufficienti
- [x] Interfaccia web locale
- [x] Test unitari e API, CI
- [x] Docker Compose locale

## Milestone 0.5 — Source Registry / discovery

- [x] Catalogo di 20 sorgenti italiane, internazionali e istituzionali
- [x] API lettura sorgenti e feed di metadati
- [x] Parser RSS/Atom/RDF e JSON API configurabile
- [x] Grant esplicito per fonte, controllo endpoint HTTPS e token amministrativo
- [x] Discovery metadata con deduplica per URL, ETag/Last-Modified e cooldown
- [x] Dashboard `/sources` e discovery `/news`
- [x] Comando CLI `--dry-run` / `--once` per tutte le fonti autorizzate
- [ ] Accordi e permessi reali per ciascuna fonte
- [ ] Verifica in rete degli endpoint e delle API partner
- [ ] Ingestion scheduler quando i permessi sono disponibili

## Milestone 0.6 — Pannello di amministrazione

- [x] /admin con UI di gestione delle fonti (create/edit/archive)
- [x] Grant e revoche documentate (metadata discovery, non AI full-text)
- [x] Provider AI OpenAI / Anthropic / Gemini con chiavi cifrate
- [x] Autenticazione a token, protezione HTTP remoto e chiavi non leggibili da API
- [x] Verifica di connettività a endpoint modelli fissi, senza inferenza
- [x] Monitoraggio ultimo stato delle sincronizzazioni e test offline
- [ ] Revisione sicurezza, RBAC, MFA, audit e rate limits prima della produzione
- [x] Collegare il provider selezionato all'estrazione strutturata delle affermazioni
- [x] Candidate ancorate al testo, revisione manuale e storico delle esecuzioni
- [ ] Estendere la pipeline al reperimento autonomo di prove e al loro confronto

## Milestone 1 — Motore serio di verifica

- [ ] PostgreSQL, Alembic e storage dei documenti con provenienza
- [ ] OAuth/OIDC, RBAC per revisori, audit log, rate limiting e moderazione
- [ ] Estrazione claims con LLM + citazioni esatte con offset nel testo originale
- [ ] Indice di ricerca, ranking delle fonti e verifica di indipendenza
- [ ] Controllo umano su affermazioni e prove; doppia revisione per casi controversi
- [ ] Calibrazione dello scoring e metriche di qualità

## Milestone 2 — Contesto e distribuzione

- [ ] Rilevamento di omissioni e confronti temporali/statistici documentati
- [ ] Traduzione IT/EN separando testo originale e resa tradotta
- [ ] Content fingerprint e cluster di eventi
- [ ] Deep link a selezioni testuali, con fallback all'URL canonico
- [ ] Estensione Chromium MV3, attiva su consenso dell'utente
- [ ] Pipeline eventi / notifiche di nuove prove e rettifiche

## Milestone 3 — Affidabilità storica e scala

- [ ] Provenienza editoriale, identificativi robusti e disambiguazione di omonimi
- [ ] Metriche su autore/testata solo con campioni idonei e audit indipendente
- [ ] Procedura di reclamo e rettifica, data retention e privacy by design
- [ ] Dashboard pubblica multi-lingua con API e analisi riproducibili

## Vincoli di prodotto

Non utilizzare un LLM come oracolo. Non confondere numero di articoli con numero di prove indipendenti. Non pubblicare punteggi sulle persone senza garanzie metodologiche e legali. Non copiare articoli o aggirare paywall. La gestione dei diritti è distinta dall'acquisizione tecnica dei contenuti.
