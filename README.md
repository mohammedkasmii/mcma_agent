# 🚗 MCMA / MAMDA Dossier Automation Agent

Complete browser automation agent for filling vehicle insurance expertise dossiers and uploading documents to the **MCMA / MAMDA SinAuto** portal (`sinauto.mamda-mcma.ma`).

---

## 📁 Project Structure & Input Folders

```
mcma_agent/
├── input_dossier/           <── Drop your dossier JSON file here (e.g. dossier.json)
│   └── dossier.json
├── input_documents/         <── Drop your 3 PDF files here
│   ├── devis.pdf            (Auto-detected as IdNature 56: Devis)
│   ├── photos_avant.pdf     (Auto-detected as IdNature 63: Photos avant)
│   └── rapport_expertise.pdf(Auto-detected as IdNature 40: Rapport)
│
├── run_dossier.py           <── Main script: run this to execute automation
├── main.py                  <── FastAPI server for web API integration
├── mapper.py                <── Field & rubric translator
├── auth_setup.py            <── One-time interactive login / session saver
└── README.md
```

---

## ⚙️ How to Setup on a New PC (2 Options)

### 🟢 Option A: 1-Click Automated Setup (Easiest)
Just double-click **[`setup_new_pc.bat`](file:///c:/Users/hp/Desktop/mcma_agent/setup_new_pc.bat)**!
It will automatically:
1. Check that Python is installed.
2. Upgrade `pip`.
3. Install all packages from `requirements.txt` (`playwright`, `pymupdf`, `fastapi`, `httpx`, `pydantic`, etc.).
4. Download and install the Playwright Chromium browser.

---

### 🟡 Option B: Manual Command-Line Setup

1. **Install Python 3.10+**: Download from [python.org](https://www.python.org/downloads/)
   * ⚠️ **IMPORTANT**: During installation, check the box: `☑ Add python.exe to PATH`.

2. **Open PowerShell / Command Prompt** in the project folder and run:
   ```powershell
   # 1. Navigate to project folder
   cd C:\path\to\mcma_agent

   # 2. Upgrade pip
   python -m pip install --upgrade pip

   # 3. Install all python dependencies
   pip install -r requirements.txt

   # 4. Install Chromium browser for Playwright
   playwright install chromium
   ```

---

## 🔑 One-Time Login (Session Setup)
Because MCMA requires SMS/OTP authentication, generate your session token once:

```powershell
python auth_setup.py
```
* Enter your username, password, and OTP in the browser window.
* As soon as you land on the dashboard, it saves `mcma_auth_state.json` and closes.
* *You won't need to log in or enter OTP again on this PC.*

---

## 🚀 How to Run

### Method 1: Zero-Config Run (Simplest)

Just drop your files in the two folders:
1. Put your JSON file inside `input_dossier/`
2. Put your 3 PDF files inside `input_documents/`
3. Run:
```powershell
python run_dossier.py
```

---

### Method 2: Custom Paths via CLI

```powershell
python run_dossier.py --json "input_dossier/custom_dossier.json" `
                      --devis "input_documents/devis.pdf" `
                      --photos "input_documents/photos_avant.pdf" `
                      --rapport "input_documents/rapport_expertise.pdf"
```

### Method 2: Via Web API (FastAPI)

1. Start the API server:
   ```powershell
   python main.py
   ```
2. Send a `POST` request to:
   ```http
   POST http://127.0.0.1:8000/api/v1/fill-dossier-from-wexia
   Content-Type: application/json

   { ... full Wexia dossier JSON ... }
   ```

---

## 🔄 Exact Automation Workflow

```
[Dossier JSON + 3 PDFs]
          │
          ▼
     [mapper.py]  ──────────► Extracts text fields, rubriques, and doc categories
          │
          ▼
  [Playwright Browser]  ────► Uses saved session state (mcma_auth_state.json)
          │
          ├── STEP 1:  Navigates to MCMA search page (/expertise/frontExpert/)
          ├── STEP 2:  Fills Reference / Matricule and clicks "Rechercher"
          ├── STEP 3:  Clicks the dossier row in search results
          ├── STEP 4:  Fills text inputs (Kilométrage, Valeur Vénale, Montant HT/TVA/TTC, etc.)
          ├── STEP 5:  Sets dropdowns (Part de responsabilité: 100%, Type de réforme: E/T)
          ├── STEP 6:  Sets checkboxes (Véhicule réparé / réformé)
          ├── STEP 7:  Adds rubriques (Pièces, Tôlerie, Mécanique, Peinture)
          ├── STEP 8:  Saves mission form (#Enregistrer)
          ├── STEP 9:  Switches to GED tab (#loadGED)
          ├── STEP 10: Compresses PDFs (PyMuPDF) and uploads each with its Nature ID
          └── STEP 11: Pauses (page.pause()) for human visual review on screen
```

---

## 📋 Field & Code Reference Mapping

### 1. Rubrique Codes (`IdRubrique`)
| Code | Rubrique Name in MCMA | Description |
| :--- | :--- | :--- |
| **`1`** | `FOURNITURES CARROSSERIE (ORIGINES)` | Spare parts (Pièces neuves d'origine) |
| **`7`** | `MAIN D'OEUVRE CARROSSERIE` | Labor: Tôlerie / Carrosserie |
| **`8`** | `MAIN D'OEUVRE MECANIQUE` | Labor: Mécanique |
| **`12`** | `MAIN D'OEUVRE PEINTURE` | Labor: Peinture |
| **`28`** | `MAIN D'OEUVRE ELECTRIQUE` | Labor: Électricité |

### 2. GED Document Nature Codes (`IdNatureDocument`)
| Code | Nature Name in MCMA | Usage |
| :--- | :--- | :--- |
| **`56`** | `DEVIS DE REPARATION GARAGE` | Repair quote PDF from repairer |
| **`57`** | `DEVIS DE REPARATION VALIDE PAR L'EXPERT` | Validated repair quote |
| **`63`** | `PHOTOS AVANT LA REPARATION` | Pre-repair damage photos PDF |
| **`40`** | `RAPPORT D'EXPERTISE PRELIMINAIRE DE REFORME` | Preliminary reform report |
| **`39`** | `RAPPORT D'EXPERTISE DE REPARATION` | Repair expertise report |
| **`6`** | `LA CARTE GRISE` | Vehicle registration document |
| **`22`** | `CONSTAT AMIABLE` | Accident report |

### 3. Main Form Inputs
| MCMA Input ID | Field Description | Source in Wexia JSON |
| :--- | :--- | :--- |
| `#Kilometrage` | Mileage in km | `vehicule.mileage_km` |
| `#ValeurVenale` | Market value (DH) | `vehicule.market_value` |
| `#MontantReparation` | Repair cost HT (DH) | `chiffrages[0].total_cost` |
| `#MontantTVA` | Tax amount (DH) | `chiffrages[0].tax_amount` |
| `#MontantTTC` | Total repair cost TTC (DH) | `chiffrages[0].final_cost` |
| `#NbreJourImmobilisation` | Immobilization days | `chiffrages[0].estimated_days` |
| `#PartResponsabilite` | Responsibility (0, 50, 100) | `dossier.responsibility_rate` |
| `#TypeReforme` | Reform type (E, T) | `dossier.reform_type` |
| `#VehRepareI` | Vehicle repaired checkbox | `dossier.repair_status` |
| `#ObservationMission` | Expert observations text | `observations_expert.texte` |
