# AFONDO — catalogo editoriale e fonti primarie

Data revisione: 19 ottobre 2026.

Il catalogo machine-readable è in [`config/source_candidates.json`](../config/source_candidates.json) (20 candidati). **Tutte le scansioni automatiche sono disabilitate** fino a un controllo di autorizzazioni, endpoint e finalità del trattamento. Un feed pubblico non è una licenza generale per scaricare, conservare, tradurre, analizzare con IA o ripubblicare articoli.

## Ruoli diversi delle fonti

- **Newsroom**: confrontare i resoconti dello stesso evento in aree geografiche diverse.
- **News agency**: risalire alla notizia distribuita a molti editori e rilevare le riprese di un solo lancio.
- **Primary evidence**: cercare documenti, comunicati, dati statistici e dichiarazioni originali. Una fonte istituzionale non costituisce automaticamente una conferma indipendente delle proprie dichiarazioni.
- **Fact-check reference**: individuare verifiche già pubblicate e approfondire fonti e contestazioni.

## Prima selezione operativa

| Fonte | Discovery | Stato per AFONDO |
|---|---|---|
| RaiNews (IT) | RSS `https://www.rainews.it/rss/tutti` | Verificare diritti AI/TDM e termini |
| Deutsche Welle (EN) | RSS `https://rss.dw.com/rdf/rss-en-all` | Verificare diritti AI/TDM e termini |
| France 24 (EN) | RSS di sezione `https://www.france24.com/en/france/rss` | Verificare diritti, individuare feed globale |
| Agência Brasil (PT/EN/ES) | Catalogo `https://agenciabrasil.ebc.com.br/feed/` | Riproduzione giornalistica condizionata; AI da chiarire |
| BBC News (EN) | RSS `https://feeds.bbci.co.uk/news/world/rss.xml` | Permesso commerciale e metadati, se applicabile |
| Euronews (EN/IT) | RSS `https://www.euronews.com/rss?format=mrss&level=theme&name=news` | Riutilizzo e raccolta massiva limitati |
| ANSA (IT/EN) | Pagina feed `https://www.ansa.it/sito/static/ansa_rss.html` | Autorizzazione specifica per uso AFONDO |
| The Guardian (EN) | Open Platform `https://open-platform.theguardian.com/` | Contratto per uso AI/TDM |
| Reuters (EN) | Reuters Connect | Contratto per accesso/uso commerciale |
| AP (EN) | AP Media API | Contratto e disponibilità secondo piano |
| ISTAT (IT) | RSS `https://www.istat.it/altri-servizi/feed-rss/` | Fonte statistica primaria, verificare riutilizzo |
| Eurostat (EN) | RSS catalogo `https://ec.europa.eu/eurostat/api/dissemination/catalogue/rss/en/statistics-update.rss` | Fonte primaria; distinguere metadata RSS e API dati |
| NASA/JPL (EN) | RSS `https://www.jpl.nasa.gov/feeds/news/` | Fonte primaria scientifica; diritti per asset |
| UN News (EN) | RSS da portale ONU | Fonte istituzionale, verificare feed e diritti |

Le testate senza feed/API verificata ma strategiche per la copertura sono **Il Post**, **Al Jazeera English**, **Africanews**, **NHK World-Japan** e **The Conversation**; **Pagella Politica** è candidata come riferimento a verifiche pubblicate. Non inventare URL o autorizzazioni mancanti.

## Fonti di riferimento consultate

- [RaiNews RSS](https://www.rainews.it/rss)
- [DW RSS (indice terzo)](https://feeder.co/de/discover/site/dw.com)
- [Euronews RSS](https://www.euronews.com/widgets) e [termini](https://www.euronews.com/terms-and-conditions)
- [ANSA RSS e limitazioni](https://www.ansa.it/sito/static/ansa_rss.html)
- [BBC condizioni d'uso (PDF)](https://downloads.bbc.co.uk/usingthebbc/bbc_terms_of_use_31March2022english.pdf)
- [AP Media API](https://api.ap.org/media/v/docs/Getting_Started_API.htm)
- [Reuters Connect](https://www.reutersconnect.com/plans-and-pricing) e [condizioni](https://www.reutersconnect.com/general-terms)
- [Guardian developer/commercial](https://open-platform.theguardian.com/access/) e [termini](https://www.theguardian.com/open-platform/terms-and-conditions)
- [Agência Brasil — riproduzione](https://agenciabrasil.ebc.com.br/sobre)
- [ISTAT feed](https://www.istat.it/altri-servizi/feed-rss/)
- [Eurostat RSS](https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-detailed-guidelines/catalogue-api/rss)
- [NASA/JPL RSS](https://www.jpl.nasa.gov/rss/)
- [UN News RSS](https://www.un.org/en/department-global-communications/news-media)
- [Pagella Politica — manifesto](https://pagellapolitica.it/manifesto)

## Strategia di selezione

Non equiparare *popolarità*, *accessibilità* o *accordo editoriale* all'affidabilità della testata. Bilanciare:

1. **Copertura geografica**: Italia, Europa, Americhe, Medio Oriente, Africa, Asia.
2. **Indipendenza delle informazioni**: gli articoli che copiano una stessa agenzia non sono prove distinte.
3. **Varietà di formato**: notizie brevi d'agenzia, approfondimenti, verifiche e documenti ufficiali.
4. **Accesso giuridicamente sostenibile**: autorizzazioni documentate per il caso d'uso e conservazione.
5. **Qualità tecnica**: URL canonici, autore, data, aggiornamenti, RSS/API stabile, rettifiche.

## Prerequisiti prima di attivare uno scanner

- Verificare licenza, termini e riserve TDM/AI **per fonte e finalità**.
- Controllare `robots.txt`, eventuali segnali applicabili, politiche di crawler e limiti di traffico: non aggirare paywall, CAPTCHA e protezioni.
- Registrare prova del permesso, URL di termini, data di controllo e durata di conservazione.
- Implementare connettori per fonte, backoff, `ETag`, `Last-Modified`, deduplica, error monitoring e kill-switch.
- Separare fase **discovery** (titolo/URL/metadati permessi) da **processing full text** (solo se legittimamente disponibile per quel trattamento).
- Conservare fonte originaria, lingua originale, timestamp, eventuale catena di riprese e versione delle condizioni.
- Mai attribuire punteggi editoriali a giornalisti/testate sulla sola base della fonte di provenienza.

## Roadmap immediata

1. Registrare criteri di utilizzo e permessi nel catalogo e ottenere conferme dai fornitori.
2. Aggiungere un `feed_validator` di sola diagnostica, non uno scraper indiscriminato.
3. Sviluppare un `source_connector` conforme per i primi feed autorizzati.
4. Normalizzare URL e metadati, raggruppare notizie dello stesso evento, riconoscere fonti derivanti dalla stessa agenzia.
5. Solo a valle: eseguire il motore AFONDO Check sulle affermazioni con prove tracciabili.
