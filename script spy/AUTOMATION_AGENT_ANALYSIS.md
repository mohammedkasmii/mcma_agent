# Comprehensive Technical Analysis & Implementation Blueprint
## MAMDA-MCMA SinAuto Automation Agent

**Target System:** `https://sinauto.mamda-mcma.ma/` (`mamda-mcma.ma`)  
**Source Reconnaissance Dataset:** `website_investigation_v6`  
**Generated Date:** August 13, 2026  

---

## 1. Executive Summary & Reconnaissance Scope

This document provides the complete, authoritative technical specification for building an automated Python agent targeting the internal insurance application **SinAuto MCMA**.

### Dataset Telemetry Overview
* **Pages Explored:** 10
* **Unique Form States:** 95
* **User Clicks Captured:** 66
* **Form Submissions:** 2
* **Total Network Requests:** 507 (78 business API calls)
* **Unique Business Endpoints:** 17 (15 form write/submission endpoints)
* **Transport Architecture:** Traditional PHP/Java enterprise web application communicating via jQuery AJAX (`X-Requested-With: XMLHttpRequest`) returning HTML fragments (`text/html`) rather than pure REST JSON APIs.

---

## 2. End-to-End Workflow Reconstruction

The full workflow reconstructed chronologically from `workflow.json`, `pages.json`, and `api_endpoints.json` consists of 6 sequential phases across 156 discrete interaction events.

```mermaid
flowchart TD
    subgraph Phase 1: Authentication & MFA
        A1["GET /SinAuto_MCMA/<br/>(Extract CSRF token)"] --> A2["POST /front/Login/login<br/>(username, password, token)"]
        A2 --> A3["POST /front/otp/verify<br/>(otp-code)"]
    end

    subgraph Phase 2: Search & Mission Discovery
        A3 --> B1["POST /expertise/FrontExpert/listeMissions<br/>(Search by Matricule/Reference)"]
        B1 --> B2["Parse HTML Response Table<br/>(Extract IdMission, IdSinistre)"]
    end

    subgraph Phase 3: Mission Hydration
        B2 --> C1["POST /expertise/gestionExpert/getMission/idMission/{IdMission}"]
        C1 --> C2["POST /expertise/gestionExpert/listeRapportDefDet<br/>(Fetch existing line items)"]
        C2 --> C3["POST /gestion/GED/natureDocuments<br/>(Fetch document categories)"]
        C3 --> C4["POST /gestion/GED/listDocuments<br/>(Fetch existing attachments)"]
    end

    subgraph Phase 4: Breakdown Line Items
        C4 --> D1["POST /gestion/reparation/listeRubriqueFactureDet/"]
        D1 --> D2["POST /expertise/gestionExpert/createRapportDefDet<br/>(Insert/Edit Line Item)"]
        D2 --> D3["POST /expertise/gestionExpert/listeRapportDefDet<br/>(Refresh Table)"]
    end

    subgraph Phase 5: Document Management (GED)
        D3 --> E1["POST /gestion/GED/ajouterDocument/IdComplement/{IdSinistre}<br/>(Multipart Binary Upload)"]
        E1 --> E2["POST /gestion/GED/ajouterDocument<br/>(Link IdFile + NatureDocument)"]
        E2 --> E3["POST /gestion/GED/listDocuments<br/>(Refresh Documents List)"]
    end

    subgraph Phase 6: Final Mission Submission
        E3 --> F1["POST /expertise/gestionExpert/expertEnregistrerMission<br/>(Submit 35-field Form)"]
        F1 --> F2["Redirect / Refresh<br/>POST /expertise/FrontExpert/listeMissions"]
    end
```

### Chronological Step Trace

| Step # | Action Type | Endpoint / Target | Trigger / Source | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| **01** | `GET` | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Initial navigation | Load login page, initialize session cookie & hidden CSRF token. |
| **02** | `POST` | `/SinAuto_MCMA/front/Login/login` | Click button "Se connecter" | Authenticate credentials (`username`, `password`, `token`). |
| **03** | `POST` | `/SinAuto_MCMA/front/otp/verify` | Click button "Soumettre" | Submit 2FA/OTP code (`otp-code`). |
| **04** | `POST` | `/SinAuto_MCMA/expertise/FrontExpert/listeMissions` | Form search / Alert link | Query missions with search filters. |
| **05** | `POST` | `/SinAuto_MCMA/expertise/gestionExpert/getMission/idMission/{id}` | Dossier row selection | Load mission details for `IdMission` (e.g. `532805`). |
| **06** | `POST` | `/SinAuto_MCMA/expertise/gestionExpert/listeRapportDefDet` | Page hydration | Fetch existing report line items. |
| **07** | `POST` | `/SinAuto_MCMA/gestion/GED/natureDocuments` | Tab switch "GED" | Load available document types (`CodeEcran`). |
| **08** | `POST` | `/SinAuto_MCMA/gestion/GED/listDocuments` | Tab switch "GED" | List attached documents for `IdComplement` (`IdSinistre`). |
| **09** | `POST` | `/SinAuto_MCMA/gestion/reparation/listeRubriqueFactureDet/` | Click "Ajouter" | Load rubric category options. |
| **10** | `POST` | `/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet` | Click save on line item | Add repair line item (`IdRubrique`, `MontantHT`, etc.). |
| **11** | `POST` | `/SinAuto_MCMA/gestion/GED/ajouterDocument/IdComplement/{id}` | Click file upload "Enregistrer" | Upload raw document binary (`multipart/form-data`). |
| **12** | `POST` | `/SinAuto_MCMA/gestion/GED/ajouterDocument` | Post-upload linkage | Associate uploaded `IdFile` with `NatureDocument`. |
| **13** | `POST` | `/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission` | Click main "Enregistrer" | Final submission of complete mission form (35 fields). |

---

## 3. Authentication & Session Strategy

### Session Model
* **Mechanism:** Classic server-side session cookies (e.g. `PHPSESSID` / container session cookie).
* **Protocol:** HTTP Form POST submissions with redirect tracking.
* **MFA Layer:** Dynamic OTP verification required immediately following primary credential verification.

### Form Fields on Login (`POST /SinAuto_MCMA/front/Login/login`)

| Field Name | Type | Value / Dynamic Status | Description |
| :--- | :--- | :--- | :--- |
| `username` | `text` | Dynamic (Credentials) | Agent login username. |
| `password` | `password` | Dynamic (Credentials) | Agent login password. |
| `token` | `hidden` | **Dynamic per session (Must Scrape)** | 15-character opaque CSRF token generated in the initial HTML DOM. |
| `hashedPassword`| `hidden` | Optional / Empty | Left empty `""` in standard browser submissions. |
| `admin` | `hidden` | Static (`""`) | Set to empty string. |

### MFA Endpoint (`POST /SinAuto_MCMA/front/otp/verify`)

| Field Name | Type | Mask / Format | Description |
| :--- | :--- | :--- | :--- |
| `otp-code` | `text` | Masked `___-___` (6 digits) | Time-sensitive One-Time Password sent via out-of-band channel. |

### Session Management Implementation
```python
import requests
from bs4 import BeautifulSoup

def authenticate(username, password, otp_provider_func):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "X-Requested-With": "XMLHttpRequest"
    })
    
    # 1. Initial GET to acquire session cookies and dynamic CSRF token
    resp = session.get("https://sinauto.mamda-mcma.ma/SinAuto_MCMA/")
    soup = BeautifulSoup(resp.text, "html.parser")
    token_input = soup.find("input", {"name": "token"})
    csrf_token = token_input["value"] if token_input else ""
    
    # 2. Submit primary credentials
    login_payload = {
        "username": username,
        "password": password,
        "token": csrf_token,
        "hashedPassword": "",
        "admin": ""
    }
    resp_login = session.post(
        "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/front/Login/login",
        data=login_payload
    )
    
    # 3. Handle OTP verification
    otp_code = otp_provider_func()
    resp_otp = session.post(
        "https://sinauto.mamda-mcma.ma/SinAuto_MCMA/front/otp/verify",
        data={"otp-code": otp_code}
    )
    return session
```

---

## 4. Endpoints & Exact Payload Schemas

### 4.1 Primary Mission Save Endpoint
* **URL:** `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/expertEnregistrerMission`
* **Schema Source:** `network` (Live network capture verified)
* **Content-Type:** `application/x-www-form-urlencoded`
* **Total Fields:** 35

| # | Field Name | Type | Suffix Meaning | Example Value / Constraints |
| :- | :--- | :--- | :--- | :--- |
| 1 | `AccordAdverse__S` | `string` | String flag | `""`, `"O"` (Oui), `"N"` (Non) |
| 2 | `DateDevis__DA` | `string` | Date (`DD/MM/YYYY`) | `"12/08/2026"` |
| 3 | `DateFinTravaux__DA` | `string` | Date (`DD/MM/YYYY`) | `"15/08/2026"` |
| 4 | `DateMECVeh__DA` | `string` | Date MEC Véhicule | `"10/05/2019"` |
| 5 | `DateRdvSoc__DA` | `string` | Date RDV Sociétaire | `"11/08/2026"` |
| 6 | `DateValDevis__DA` | `string` | Date Validation Devis | `"13/08/2026"` |
| 7 | `Depasse20000__S` | `string` | String flag | `""`, `"O"`, `"N"` |
| 8 | `Epaviste__S` | `string` | Text string | Name of wreck buyer / buyer entity |
| 9 | `HeureFinTravaux__S`| `string` | Time string | `"17:00"` |
| 10| `HeureRdv__S` | `string` | Time string | `"10:30"` |
| 11| `IdMission__I` | `string` | Integer (ID) | Chained `IdMission` (e.g. `"532805"`) |
| 12| `IdSinistre__I` | `string` | Integer (ID) | Chained `IdSinistre` (e.g. `"810692"`) |
| 13| `IsConfirmMTACM__S`| `string` | String flag | `""`, `"O"`, `"N"` |
| 14| `Kilometrage__I` | `string` | Integer | `"124500"` |
| 15| `MontantChargeMutuelle__M` | `string` | Monetary | `"4200.00"` |
| 16| `MontantChargeSocietaire__M`| `string` | Monetary | `"0.00"` |
| 17| `MontantDommage__M` | `string` | Monetary | `"4200.00"` |
| 18| `MontantEpave__M` | `string` | Monetary | `"0.00"` |
| 19| `MontantFranchise__M`| `string` | Monetary | `"0.00"` |
| 20| `MontantRemise__M` | `string` | Monetary | `"0.00"` |
| 21| `MontantReparation__M`| `string` | Monetary | `"3500.00"` |
| 22| `MontantTVA__M` | `string` | Monetary | `"700.00"` |
| 23| `MontantVetuste__M` | `string` | Monetary | `"0.00"` |
| 24| `MotifDesaccord__S` | `string` | Text string | Reason for disagreement if applicable |
| 25| `NbreJourImmobilisation__I` | `string` | Integer | `"3"` |
| 26| `ObservationMission__S` | `string` | Textarea string| General expert observations |
| 27| `OffreEpave__M` | `string` | Monetary | `"0.00"` |
| 28| `RappCarence__S` | `string` | String flag | `""`, `"O"`, `"N"` |
| 29| `ReferenceDossier__S`| `string` | Text string | Claim reference number |
| 30| `TelEpaviste__S` | `string` | Phone string | Contact number |
| 31| `TvaRecup__S` | `string` | String flag | `""`, `"O"`, `"N"` |
| 32| `TypeReforme__S` | `string` | Select value | `""`, `"E"`, `"T"` |
| 33| `ValeurVenaleEstime__M` | `string` | Monetary | `"85000.00"` |
| 34| `ValeurVenale__M` | `string` | Monetary | `"85000.00"` |
| 35| `VehReforme__S` | `string` | String flag | `""`, `"O"`, `"N"` |

---

### 4.2 Breakdown Line Item Creation (`createRapportDefDet`)
* **URL:** `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/expertise/gestionExpert/createRapportDefDet`
* **Schema Source:** `network` (Live network capture verified)

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `IdMission` | `string` | Parent mission ID (`532805`). |
| `IdRapportDefDet`| `string` | Detail item ID (empty `""` on new insert, ID on edit). |
| `IdRubrique` | `string` | Heading ID from `1` to `28`. |
| `LibRubrique` | `string` | Human-readable label matching rubric ID. |
| `MontantHT` | `string` | Pre-tax amount (e.g. `"1200.00"`). |
| `MontantTTC` | `string` | Total including VAT. |
| `MontantVetuste` | `string` | Depreciation reduction. |
| `TauxVetuste` | `string` | Depreciation rate (`0%` to `100%`). |
| `Taxe` | `string` | VAT rate (`20%`, etc.). |
| `edit` | `string` | `"0"` for creation, `"1"` for modification. |
| `delete` | `string` | `"0"` (default) or `"1"` for deletion. |

---

### 4.3 Document Metadata Registration (`ajouterDocument`)
* **URL:** `POST https://sinauto.mamda-mcma.ma/SinAuto_MCMA/gestion/GED/ajouterDocument`
* **Schema Source:** `network` (Live network capture verified)

| Field Name | Type | Description |
| :--- | :--- | :--- |
| `CodeEcran` | `string` | Screen/context code (e.g. `"EXPERT"`). |
| `IdComplement` | `string` | The claim/sinistre identifier (`IdSinistre`). |
| `IdFile` | `string` | Numeric file ID returned by upload step. |
| `NatureDocument`| `string` | Document type classification ID (e.g. `"6"` for Carte Grise). |

---

## 5. Chained Identifiers & Data Threading

| Source Location | Extracted Variable | Target Endpoint | Target Parameter |
| :--- | :--- | :--- | :--- |
| Search Results Table (`listeMissions`) | **`IdMission`** | `getMission/idMission/{IdMission}` | Route URL param |
| Search Results Table (`listeMissions`) | **`IdMission`** | `listeRapportDefDet` | `IdMission` |
| Search Results Table (`listeMissions`) | **`IdMission`** | `createRapportDefDet` | `IdMission` |
| Search Results Table (`listeMissions`) | **`IdMission`** | `expertEnregistrerMission` | `IdMission__I` |
| Mission HTML / Hidden input | **`IdSinistre`** | `expertEnregistrerMission` | `IdSinistre__I` |
| Mission HTML / Hidden input | **`IdSinistre`** | `ajouterDocument/IdComplement/{id}` | Route URL param |
| Mission HTML / Hidden input | **`IdSinistre`** | `ajouterDocument` | `IdComplement` |
| Mission HTML / Hidden input | **`IdSinistre`** | `listDocuments` | `IdComplement` |
| Binary Upload Response | **`IdFile`** | `ajouterDocument` | `IdFile` |
| Screen DOM Context | **`CodeEcran`** | `natureDocuments`, `listDocuments`, `ajouterDocument` | `CodeEcran` |

---

## 6. Complete Enumerations & Dropdown Values

All valid values extracted directly from `forms.json`. Server-side validation will reject any submission outside these sets.

### 6.1 `TypeMission__S` (Search Filter)
* `""`: All / Unfiltered
* `"A"`: ARBITRAGE
* `"C"`: CONTRADICTOIRE
* `"E"`: ESTIMATION RÉPARATION
* `"G"`: GARAGE RÉPARATEUR
* `"J"`: JUDICIAIRE
* `"N"`: EXPERTISE
* `"V"`: ESTIMATION VALEUR VÉNALE

### 6.2 `Modereparation__I` (Search Filter)
* `""`: All / Unfiltered
* `"N"`: MODE NORMAL
* `"C"`: GARAGE CONVENTIONNÉ
* `"A"`: AMANE AUTO EXPRESS
* `"S"`: SUPER EXPRESS
* `"B"`: SERVICE A DOMICILE BALI HANI
* `"T"`: TELE-EXPERTISE

### 6.3 `PartResponsabilite` (Liability Allocation)
* `"0"`: 0%
* `"50"`: 50%
* `"100"`: 100% (Default Selected)

### 6.4 `TypeReforme__S` (Vehicle Reform Classification)
* `""`: Non-reformed / Standard Repair
* `"E"`: Économique (Economic Total Loss)
* `"T"`: Technique (Technical Total Loss)

### 6.5 `IdRubrique` (Complete 28 Repair Headings)

| Value | Rubric Description | Value | Rubric Description |
| :--- | :--- | :--- | :--- |
| `"1"` | FOURNITURES CARROSSERIE (ORIGINES) | `"15"` | FOURNITURES ÉLÉCTRIQUES (RÉCUPÉRABLES) |
| `"2"` | FOURNITURES CARROSSERIE (ADAPTABLES) | `"16"` | PEINTURES ET INGRÉDIENTS |
| `"3"` | FOURNITURES CARROSSERIE (RÉCUPÉRABLES) | `"17"` | PASSAGE AU MARBRE |
| `"4"` | FOURNITURES MÉCANIQUE (ORIGINES) | `"18"` | PARALLÉLISME ET ÉQUILIBRAGE |
| `"5"` | FOURNITURES MÉCANIQUE (ADAPTABLES) | `"19"` | RÉPARATION VITRE |
| `"6"` | FOURNITURES MÉCANIQUE (RÉCUPÉRABLES) | `"20"` | REMPLACEMENT VITRE |
| `"7"` | MAIN D'OEUVRE CARROSSERIE | `"21"` | RÉPARATION PARE-BRISE |
| `"8"` | MAIN D'OEUVRE MÉCANIQUE | `"22"` | REMPLACEMENT PARE-BRISE |
| `"9"` | MONTANT TOTAL | `"23"` | RÉPARATION LUNETTE ARRIÈRE |
| `"10"` | FOURNITURES PEINTURE ET INGRÉDIENT (ORIGINES) | `"24"` | REMPLACEMENT LUNETTE ARRIÈRE |
| `"11"` | FOURNITURES PEINTURE ET INGRÉDIENT (ADAPTABLES) | `"25"` | COLLE |
| `"12"` | MAIN D'OEUVRE PEINTURE | `"26"` | KIT DE COLLE PB ET LA |
| `"13"` | FOURNITURES ÉLÉCTRIQUES (D'ORIGINE) | `"27"` | KIT DE COLLE VITRE |
| `"14"` | FOURNITURES ÉLÉCTRIQUES (ADAPTABLES) | `"28"` | MAIN D'OEUVRE ÉLÉCTRIQUE |

### 6.6 Key `NatureDocument` (Document Types in GED)
*(Common types from the 154 categories in `forms.json`)*:
* `"6"`: LA CARTE GRISE
* `"10"`: PERMIS DE CONDUIRE
* `"11"`: LA CARTE VERTE
* `"36"`: PV
* `"39"`: RAPPORT D'EXPERTISE DE RÉPARATION
* `"40"`: RAPPORT D'EXPERTISE PRÉLIMINAIRE DE RÉFORME
* `"41"`: RAPPORT D'EXPERTISE DÉFINITIF DE RÉFORME
* `"62"`: PHOTOS DE L'ACCIDENT
* `"63"`: PHOTOS AVANT LA RÉPARATION
* `"64"`: PHOTOS APRÈS RÉPARATION
* `"162"`: RAPPORT D'EXPERTISE

---

## 7. Gaps, Unknowns & Edge Cases

1. **AJAX Response Format**:
   - The application does not return JSON on `listeMissions` or `getMission`. Responses are HTML table fragments.
   - *Mitigation*: Agent must use BeautifulSoup / CSS selectors (e.g. `tr[data-id]`, `td.idMission`) to parse search results.
2. **OTP Extraction**:
   - `POST /SinAuto_MCMA/front/otp/verify` requires a live OTP. The agent must support either an interactive CLI prompt, an email/IMAP polling hook, or an SMS gateway listener.
3. **Multipart Binary Upload Protocol**:
   - In `requests.jsonl`, `POST /gestion/GED/ajouterDocument/IdComplement/{IdSinistre}` uses `multipart/form-data; boundary=----WebKit...` with standard binary payload.
   - *Field Name*: Form definition specifies `<input type="file" name="document" id="document">`.

---

## 8. Recommended Agent Architecture

A **Hybrid Architecture** provides optimal speed, reliability, and maintainability:

```
[Agent Entrypoint]
       │
       ├── Phase 1: Authentication & MFA ──► Playwright Browser Engine
       │                                     - Solves OTP & JS token generation
       │                                     - Extracts session cookies
       │
       └── Phase 2: Core Business Logic  ──► Direct HTTP (requests / httpx)
                                             - Search missions
                                             - Fetch & thread IDs
                                             - Add breakdown line items
                                             - Upload documents (multipart)
                                             - Save mission form (35 fields)
```

---

## 9. "Ready to Build" Checklist

- [x] Confirmed login parameter list (`username`, `password`, `token`, `hashedPassword`, `admin`)
- [x] Confirmed session cookie management strategy
- [x] Confirmed 35-field payload schema for `expertEnregistrerMission`
- [x] Confirmed 11-field payload schema for `createRapportDefDet`
- [x] Confirmed 4-field payload schema for `ajouterDocument`
- [x] Extracted complete static enumerations (28 rubrics, mission types, reform types, liability splits)
- [x] Mapped all chained variables (`IdMission`, `IdSinistre`, `IdFile`, `CodeEcran`)
- [ ] Implement OTP receipt handler (interactive prompt or webhook)
- [ ] Implement HTML scraper for mission search results table
