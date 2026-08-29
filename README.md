# 🚗 MCMA / MAMDA Dossier Automation Agent

Complete browser automation agent for filling vehicle insurance expertise dossiers and uploading documents to the **MCMA / MAMDA SinAuto** portal (`sinauto.mamda-mcma.ma`).

---

## 🔔 Centre de Notifications (Phase 1 — opérationnel)

Hub multi-comptes qui surveille les alertes des 4 profils portail et suit le travail des employés.

```powershell
python -m db.migrate     # une seule fois : cree la base et importe l'existant
python main.py           # demarre le serveur + le poller automatique
```

| Capacité | Détail |
| :--- | :--- |
| **4 comptes** | MCMA/MAMDA × Oujda/Nador, session et carte d'état par compte |
| **Poller automatique** | Toutes les 5 min, **uniquement 07h45–18h00** (`Africa/Casablanca`) |
| **SQLite (WAL)** | `data/mcma.db` — fin des pertes d'écriture concurrentes |
| **Cycle de vie double** | Présence portail vs statut employé, séparés : une alerte archivée **garde ses notes** |
| **Flux delta** | `GET /api/v1/state?since=<version>`, interrogé toutes les 15 s |
| **Attribution** | Nom de l'employé enregistré sur chaque changement |

### Endpoints principaux

| Endpoint | Rôle |
| :--- | :--- |
| `GET /api/v1/state?since=` | Flux delta des sinistres + fenêtre + comptes |
| `GET /api/v1/accounts` | Les 4 cartes : santé de session, dernière synchro |
| `POST /api/v1/accounts/{id}/login` | Ouvre la fenêtre OTP **sur le PC serveur** |
| `POST /api/v1/accounts/{id}/validate` | Vérification headless de la session |
| `POST /api/v1/refresh` | Synchronisation manuelle (verrou par compte) |
| `POST /api/v1/employee-actions` | Statut + note + auteur |

📘 **Installation à l'agence : voir [`docs/GUIDE_INSTALLATION_AGENCE.md`](docs/GUIDE_INSTALLATION_AGENCE.md).**

---

## ⚠️ Module de remplissage automatique — DÉSACTIVÉ

Le **centre de notifications** (`python main.py` → http://localhost:8000) est la fonctionnalité active et prise en charge.

Le **module de remplissage automatique des formulaires** (Mode Normal / Mode Conventionné) est présent dans le code mais **désactivé**. Il n'est pas encore autorisé à agir sur le portail MCMA/MAMDA. Concrètement :

| Point d'entrée | Comportement |
| :--- | :--- |
| `POST /api/v1/fill-dossier` | `503` + message explicatif |
| `POST /api/v1/fill-dossier-from-wexia` | `503` + message explicatif |
| `python -m tools.run_dossier` | Refuse et quitte (code 2) |
| ~~`menu.py`~~ (supprimé) | Marquée `[DESACTIVE]` |
| `POST /api/v1/map-wexia-dossier` | ✅ **reste disponible** — traduction Wexia → MCMA, hors ligne, sans navigateur |

Le drapeau est défini à un seul endroit : [`core/features.py`](core/features.py). Pour le déverrouiller (développeurs uniquement) :

```powershell
$env:MCMA_ENABLE_FORM_FILLING = "1"; python main.py
```

Voir `docs/PROJECT_ARCHITECTURE_BLUEPRINT.md` §11 et §15 pour les conditions de réactivation.

---

## 📁 Structure du projet

```
mcma_agent/
├── main.py                     point d'entree : construit l'app, lance uvicorn
├── DEMARRER_MCMA.bat           <- ce que l'agence double-clique
├── Ouvrir_MCMA_Employe.bat     raccourci employe (+ .url)
│
├── api/          couche HTTP : system, state, accounts, filling
├── workflows/    orchestrations metier (process_workflow)
├── portal/       tout ce qui parle au portail MCMA (fetch, extractor, poller, auth)
├── browser/      mecanique Playwright uniquement (DOM, formulaires, securite)
├── db/           seule couche qui touche SQLite (schema, repository, migrate)
├── mapper/       Wexia JSON -> contrat MCMA (pur, deterministe)
├── core/         config, constantes, fenetre horaire, drapeaux de fonctionnalites
├── static/       tableau de bord (aucune etape de build)
├── tests/        57 tests
│
├── docs/         blueprint, guide d'installation, analyses
├── scripts/      installation et maintenance (.bat)
└── tools/        utilitaires developpeur (CLI hors service)
```

**Sens des dependances**, du haut vers le bas — jamais l'inverse :

```
api  ->  workflows  ->  portal  ->  browser  ->  core
                    ->  db      ->  core
                    ->  mapper  ->  core
```

`core/` n'importe rien. Aucun cycle.

---

## ⚙️ How to Setup on a New PC (2 Options)

### 🟢 Option A: 1-Click Automated Setup (Easiest)
Just double-click **[`scripts/setup_new_pc.bat`](file:///c:/Users/hp/Desktop/mcma_agent/setup_new_pc.bat)**!
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
python -m tools.auth_setup
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
python -m tools.run_dossier
```

---

### Method 2: Custom Paths via CLI

```powershell
python -m tools.run_dossier --json "input_dossier/custom_dossier.json" `
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
