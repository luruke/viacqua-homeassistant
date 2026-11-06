# Viacqua customer portal – reverse-engineered API

Reverse-engineered on 2026-11-06 from a real, logged-in session. Portal:
<https://sol.viacqua.it/CRM_20_Multi/Ingresso_Home.aspx>.

## TL;DR

- **No JSON API.** The portal is an ASP.NET WebForms app (the "blucrm" CRM, jQuery 1.8.3, "optimised for IE9"). Every action is either a `GET` of an `.aspx` page or a **postback**: a `POST` of the page's whole form, including `__VIEWSTATE`, `__VIEWSTATEGENERATOR` and `__EVENTVALIDATION`, with `__EVENTTARGET` and `__EVENTARGUMENT` set.
- **Auth** is a forms-auth cookie (HttpOnly) set by the login POST. When the session expires, any page **302-redirects to `Ingresso_Home.aspx`** and returns HTTP 200 with the login form. Detect it by checking for `boxLogin$Login1$UserName` in the HTML.
- **Data granularity:** meter readings come only about **every 6 months** (periodic readings, ~January and ~July). Bills are quarterly. There is no daily or hourly data. The smart LoRaWAN meters aren't exposed here yet.
- Cloudflare sits in front of the site (`/cdn-cgi/...`). E-mail addresses in pages are obfuscated with `data-cfemail` (XOR, first byte is the key). `parsers.decode_cfemail` decodes them.
- Google Analytics is loaded on every page. Ignore it.

Base URL: `https://sol.viacqua.it/CRM_20_Multi/`

## Login

1. `GET Ingresso_Home.aspx` to collect the hidden fields.
2. `POST Ingresso_Home.aspx` (`application/x-www-form-urlencoded`):

| field | value |
|---|---|
| `__EVENTTARGET` | `""` |
| `__EVENTARGUMENT` | `""` |
| `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` | from step 1 |
| `boxLogin$Login1$UserName` | username |
| `boxLogin$Login1$Password` | password |
| `boxLogin$Login1$RememberMe` | `on` (optional) |
| `boxLogin$Login1$LoginButton` | `Entra` |

3. Success: `302 → Home/landingPage.aspx → 302 → Home/Edit_Home.aspx`. The logged-in name is in `#boxHeader_boxHeader1_lblUtenteCollegato`.
   Failure: the login page comes back again, and the error is presumably in `#boxLogin_Login1_loginerror` (not observed yet).

Logout: `GET Login/LogOut.aspx`.

Other links in the header: `Amministrazione/ModificaPassword2.aspx` (change password) and `CambiaServizio.aspx?srv=AC` (switch service; only **AC = Acqua** exists).

## Menu / pages

The `id=` query param is the menu id. It's harmless, but keep it as is.

| Menu | URL | What |
|---|---|---|
| Home | `Home/Edit_Home.aspx?id=2` | Shortcut buttons (`boxAreaSponsor$btnBollette`, `btnConsumi`, `btnAutoconsumo`, `btnDomiciliazione`, `btnModificaContatti`, `btnNucleoFamiliare`) and an "Avvisi" (notices) box, which was empty |
| Anagrafica | `Anagrafica/Ricerca_Anagrafica.aspx?id=3` | Customer data (DetailsView `#dv`) |
| Fatture | `Bollette/VisualizzaBollette.aspx?id=17` | Bills grid `#gv`, 10 per page, with PDF download |
| Consumi | `Consumi/ConsumiWebGas.aspx?id=19` | Meter readings grid `#gv`, 10 per page |
| AutoLettura | `AutoConsumo/AutoLettura.aspx?id=22` | Self-reading form, with the previous reading and the allowed range |
| Contratti | `Contratti/VisualizzaContratti.aspx?id=24` | Contracts grid `#gv` → detail page |
| Modulistica | `Documenti/Documenti_Visualizza.aspx?id=4` | Static forms/documents (not explored) |
| Storico richieste | `Attivita/StatoAttivita.aspx?id=25` | Request history (free text) |
| Contattaci | `Contattaci/Contattaci.aspx?id=100` | Contact form (not explored, write action) |

## Grids and pagination

All lists are ASP.NET `GridView`s with `id="gv"`. The pager is the last row and holds a nested `<table>`. The current page is a `<span>`, and the other pages are `<a href="javascript:__doPostBack('gv','Page$N')">`.

To get page N, POST to the same URL with all form fields plus `__EVENTTARGET=gv` and `__EVENTARGUMENT=Page$N`. **Always post using the viewstate of the page you are currently on.**

Column sorting works the same way: `__EVENTARGUMENT=Sort$<Column>`.

## Consumi – meter readings

`GET Consumi/ConsumiWebGas.aspx?id=19`

- `select[name=ddlContratto]` lists contracts, with values like `201919000001` and labels like `2019-19000001`. Changing it triggers an auto-postback with `__EVENTTARGET=ddlContratto`.
- Columns of grid `#gv`:

| # | header | sort key | example | notes |
|---|---|---|---|---|
| 0 | POD/PDR | `POD` | `0502400000000001` | supply point |
| 1 | Codice PDE | `idSede` | `70000001` | |
| 2 | Data Lettura | `DataLettura` | `17/07/2026` | dd/mm/yyyy |
| 3 | Lettura | `Lettura` | `857` | cumulative meter index, m³ |
| 4 | Consumo | `Consumo` | `78` | m³ since the previous reading |
| 5 | Tipo Lettura | `Tipo` | `Periodica` / `Apertura` | `Apertura` = contract start, reading 0 |
| 6 | Matricola | `Matricola` | `20000001` | meter serial |
| 7 | Nro Fattura | `NumeroFattura` | `768076` or `-` | bill that charged it |
| 8 | del | `DataEmissione` | `13/08/2026` or `-` | bill date |
| 9 | (hidden `.nascondi`) IdSede Ori / "Periodo competenza" | `IdSede_Ori` | `70000001` | |
| 10 | (hidden) consorzio | `FonteDato` | empty | |

Observed: 19 rows from 05/04/2019 (Apertura) to 17/07/2026, two pages. Each year has a "31/12" row with consumption 0 and no bill; these look like year-end interpolated cut-offs.

## Fatture – bills

`GET Bollette/VisualizzaBollette.aspx?id=17`

Columns of grid `#gv`:

| # | header | example | notes |
|---|---|---|---|
| 0 | Fattura | `768076` | |
| 1 | Competenza al | `202607` | YYYYMM |
| 2 | Emissione | `13/08/2026` | |
| 3 | Scadenza | `14/09/2026` | due date |
| 4 | Servizio | `AC` | |
| 5 | Importo | `212,65 €` | Italian number format |
| 6 | Pagato | `<input type=checkbox disabled [checked]>` | paid flag |
| 7 | Residuo | `159,49` | outstanding amount |
| 8 | PDF | `<input type=submit name="gv$ctlNN$btnDownload" value="Scarica">` | |

- **PDF download:** POST the grid page with all fields plus `gv$ctl02$btnDownload=Scarica`, with `__EVENTTARGET` empty. The response is a `302 → Download.aspx?f=<opaque base64 token>` that serves `application/pdf` with `Content-Disposition: attachment; filename=<year>_<number>.pdf`. Control names restart from `ctl02` on **every** page, so first post the `Page$N` postback, then click the button.
- The PDF (around 1 MB, ~12 pages) contains things the HTML doesn't: a cost breakdown (Quota Fissa, Acquedotto, Fognatura, Depurazione, Oneri di Perequazione, IVA), measured vs. estimated consumption with date ranges, meter type (e.g. `C19`), tariff type, and the self-reading phone number. These could be parsed later with `pdftotext` or `pypdf` for cost-per-m³ sensors.
- **`btnExportCSV`** (image button) is broken. Posting `btnExportCSV.x/.y` just re-renders the page.
- Filters, all text fields under `boxParametriRicerca$lvParametriRicerca$`: `txtPeriodo`, `txtCodicePod`, `txtNumeroFattura`, `txtDataEmissioneInizio`, `txtDataEmissioneFine`, applied with `btnFiltra=Cerca`. Not needed; paging over everything is cheap (28 bills fit on 3 pages).

## Contratti – contracts

`GET Contratti/VisualizzaContratti.aspx?id=24`. Grid columns: Codice Nominativo, Numero Contratto, Ragione sociale, Servizio, Anno Contratto, Inizio Contratto, Fine Contratto, and the button `gv$ctl02$btnDettaglio` ("Vedi dettaglio").

Clicking the button (postback with `gv$ctl02$btnDettaglio=Vedi dettaglio`) gives `302 → Contratti/ContrattiDettaglioAC.aspx?par=<opaque token>`. That page has jQuery-UI tabs, each a DetailsView of `<td class=table_header>key</td><td>value</td>` rows:

- `#tabs-1` / `#dvContratto`: Codice Nominativo, Numero Contratto, Nominativo spedizione, **Stato contratto**, Indirizzo spedizione, Indirizzo Fornitura, Modalità pagamento (`RID`), Tipo Invio, Email Invio, **Periodicità fatturazione** (`TRIMESTRALE`), Domiciliazione (bank + IBAN), Tipologia Appartenenza, Mercato, **Uso** (tariff class), **Volume Annuale** (m³/year, 84)
- `#tabs-2` / `#dvPdr`: Provincia, Comune, Cap, Localita, Numero Contratto, Data Inizio, Data Fine, PDR
- `#tabs-3` / `#dvCatasto`: Indirizzo Immobile, Codice Catastale, Comune, Tipo Unita, Sezione Urbana, Foglio, Particella, SubAlterno, ...
- `#tabs-4..6`: Agevolazioni, Sconti, Promozioni. All empty for this account.

## Anagrafica – customer

DetailsView `#dv`: Codice Nominativo, Nominativo, Telefono, Cellulare, Codice fiscale, Partita IVA, E-mail (cf-obfuscated), Indirizzo, Comune, CAP, Provincia, Servizio.

## AutoLettura – self reading (write)

`GET AutoConsumo/AutoLettura.aspx?id=22`

| element | meaning |
|---|---|
| `select ctrlAutoLetture1$ddlContratto` | value `2019-19000001N` (note the trailing `N`) |
| `#ctrlAutoLetture1_lblTipoLetturaDescr` | `Periodica` |
| `#ctrlAutoLetture1_lblDataLetturaPrecDescr` | previous reading date |
| `#ctrlAutoLetture1_lblLettPrecedenteDescr` | previous reading (m³) |
| `#ctrlAutoLetture1_lblLetturaStimataDescr` | `da 857 a 905`, the allowed range |
| hidden `ctrlAutoLetture1$HFrangemax` | `905`, upper bound |
| hidden `ctrlAutoLetture1$HFcodCliente` | customer code |
| `ctrlAutoLetture1$txtDataLetturaDescr` | today's date (prefilled) |
| `ctrlAutoLetture1$txtLettura` | **the reading to submit**, integer (validator regex `^([0-9]{1...`) |
| `ctrlAutoLetture1$btnConfermaLettura` | `Conferma` |
| `#ctrlAutoLetture1_lblmsgavviso` | result/warning message |

Submit: postback with `ctrlAutoLetture1$txtLettura=<n>` and `ctrlAutoLetture1$btnConfermaLettura=Conferma`. **Not exercised**, since it would send a real reading. `ViacquaClient.submit_self_reading()` implements it behind `confirm=True`.

The upper bound of the range also works as Viacqua's "expected maximum" for the period.

## Storico richieste

`.elencoAttivita` holds free text separated by `<br>`, e.g. `Richiesta di Sepa evasa il 12/18/2019 alle ore 8:21 AM`. Note the US date format here.

## Ideas for the Home Assistant integration

- **Water statistic:** import every reading as an external statistic (`sum` = cumulative m³ = `Lettura`) at the reading date, so the HA Energy → Water dashboard shows the semi-annual history back to 2019. Interpolating daily values between readings is possible but would be made-up data. Better to keep real points only.
- **Sensors:** last meter reading (m³, `total_increasing`, `device_class: water`), last reading date, last period consumption, annual volume (contract), latest bill amount / due date / outstanding, total outstanding, number of unpaid bills, self-reading allowed range.
- **Service** `viacqua.submit_reading`: pair it with an ESPHome water meter to send the self reading automatically.
- **Polling:** data changes a few times a year, so polling every 12–24 h is plenty.
- Use one `aiohttp` session per config entry with its own cookie jar (`async_create_clientsession(hass)`).
