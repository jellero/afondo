# AFONDO Lens — preview Chrome

1. Avvia l'API AFONDO su http://127.0.0.1:8000.
2. Vai a `chrome://extensions`, abilita *Developer mode*.
3. Clicca *Load unpacked* e seleziona la cartella `extension`.
4. Apri un articolo HTTP/HTTPS, clicca sull'icona AFONDO e poi *Analizza questa pagina*.
5. L'estensione copia il testo visibile nel **server locale** e apre l'analisi.

### Limitazioni

Questa è una preview per sviluppatori, non un'estensione pronta per Chrome Web Store. L'estrazione usa `article`, `main` o `body`; potrebbe includere testi di menu o esclusi dal contesto. Le pagine protette, script-injected o dinamiche potrebbero non essere accessibili. L'estensione non opera in background, non registra la navigazione e non aggira paywall. Prima di un rilascio pubblico: politiche di privacy, gestione diritti, sicurezza API, limite dei dati inviati, miglioramento dell'estrazione, UX per consenso e controllo da parte del lettore.
