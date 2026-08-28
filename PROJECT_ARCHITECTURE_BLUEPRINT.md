# 🏛️ PROJECT ARCHITECTURE SPECIFICATION & SYSTEM DESIGN BLUEPRINT
**Project:** MCMA / MAMDA Auto Insurance RPA & Notification Operations Engine  
**Target Environment:** Local Agency On-Premise Server (Wexia ERP Ecosystem)  
**Version:** 2.0 Architectural Specification  
**Date:** August 2026  

---

## 1. Executive Summary & Project Context

The **MCMA / MAMDA Automation & Notification Agent** is an enterprise RPA (Robotic Process Automation) and operations hub built to automate insurance expertise workflows, track incoming notifications across multiple accounts, and populate expertise reports on the Moroccan insurance portal (`sinauto.mamda-mcma.ma`).

The application is deployed on an **on-premise local server** within the agency network (alongside the agency's **Wexia ERP** instance). Multiple non-technical agency employees connect to this system via local network browsers to manage incoming claims, track actions, and execute automated filings.

---

## 2. Business Scope & Multi-Tenant Multi-Account Requirements

The system must seamlessly handle **4 distinct insurance portal accounts** representing 2 insurance entities across 2 geographical agencies:

| Account ID | Entity | Agency City | Target Portal Base URL | Primary Workflow Scope |
|:---|:---:|:---:|:---|:---|
| **`mcma_oujda`** | MCMA | Oujda | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |
| **`mamda_oujda`** | MAMDA | Oujda | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |
| **`mcma_nador`** | MCMA | Nador | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |
| **`mamda_nador`** | MAMDA | Nador | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |

> **Key Portal Insight:** Both MCMA and MAMDA share the exact same underlying software platform and domain (`sinauto.mamda-mcma.ma`). The difference between entities and agencies lies strictly in the **authentication credentials**, **session cookies**, and **assigned claim databases**.

---

## 3. Core System Functional Modules

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                           AGENCY LOCAL NETWORK (WIFI / ETHERNET)                       │
│                                                                                       │
│   Employee Laptop 1             Employee Laptop 2               Employee Mobile       │
│   (http://192.168.1.X:8000)     (http://192.168.1.X:8000)     (http://192.168.1.X:8000)│
└───────────▲─────────────────────────────▲──────────────────────────────▲──────────────┘
            │                             │                              │
            └─────────────────────────────┼──────────────────────────────┘
                                          │ HTTP / WebSockets / SSE
                                          ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                    LOCAL AGENCY SERVER (FastAPI Python Host Engine)                   │
│                                                                                       │
│  ┌────────────────────────┐  ┌────────────────────────┐  ┌─────────────────────────┐  │
│  │ Module 1:              │  │ Module 2:              │  │ Module 3:               │  │
│  │ Multi-Account          │  │ Employee Workflow &    │  │ Form Filling Agent      │  │
│  │ Notification Extractor │  │ Action Tracking Engine │  │ (Wexia JSON -> Portal)  │  │
│  └───────────┬────────────┘  └───────────┬────────────┘  └────────────┬────────────┘  │
│              │                           │                            │               │
│              └───────────────────────────┼────────────────────────────┘               │
│                                          ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │                         State Vault & Session Storage                           │  │
│  │  - auth_sessions/*.json (4 Playwright Auth States)                              │  │
│  │  - claim_registry.json (Accumulative Notification Store & History)              │  │
│  │  - employee_actions.json (Action Statuses: TODO, IN_PROGRESS, DONE, WAITING)    │  │
│  └───────────────────────────────────────┬─────────────────────────────────────────┘  │
└──────────────────────────────────────────┼────────────────────────────────────────────┘
                                           │ Encrypted Sessions / Playwright Chromium
                                           ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                             REMOTE MAMDA / MCMA PORTAL                                │
│                            (sinauto.mamda-mcma.ma)                                    │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

### Module 1: Multi-Account Notification & Alert Engine (Phase 1 Focus)
- **Navbar Category Discovery**: Inspects `#listeAlertes` for active categories (`MISSIONS (FACTURES REÇUES)`, `DEVIS GARAGES TRAITÉS`, `RELANCES`, `RAPPORTS PRÉLIMINAIRES`, etc.).
- **High-Speed Extractor**: Uses direct in-page asynchronous AJAX calls (`POST /getAlerte/CodeAlerte/{id}`) with full-dataset parameters (`length: -1`), extracting 80+ records across 8 categories in **<2 seconds** without reloading pages.
- **Auto Keep-Alive Daemon**: Background poller that maintains active sessions 24/7.

### Module 2: Employee Action & Workflow Tracking Engine
- **Lifecycle Tracking**: Employees mark claim notifications as:
  - ⚪ `À Traiter` *(Default / Pending)*
  - 🔵 `En Cours` *(Being handled by an employee)*
  - 🟢 `Traité / Terminé` *(Completed — visually dimmed on table)*
  - 🟡 `En Attente` *(Waiting for external accord/info)*
- **Internal Remarks / Notes**: Employees attach custom notes (e.g. *"Facture saisie sur Wexia"*, *"Expert relancé"*).
- **Multi-Employee Sync**: Action statuses and notes are synchronized across all connected agency browsers in real time.

### Module 3: Form Filling & Expertise Agent (Phase 2 Focus)
- **Wexia Data Mapping**: Deterministic business mapper (`WexiaToDossierMapper`) translating raw Wexia JSON into MCMA contract format.
- **Dual Repair Mode Engines**:
  - **Mode Normal**: Header fields + `#tableRapportDet` line items with automatic tax & labor calculation.
  - **Mode Conventionne**: Table 2 (`#DevisDetTableVal`) exact line-item matching against pre-existing garage line estimates.
- **Safety Interceptor**: Route interceptor blocking network write methods during testing (`createDevisDet`, `deleteDevisDet`, `garageModifierValDevis`, `cloturerMission`, `enregistrerMission`, `validerDevis`).

---

## 4. Architectural Challenges & Open Technical Questions for Discussion

### Question 1: Standalone Frontend Architecture (Next.js / Vite vs. Served Dashboard)
- **Current Setup**: Vanilla JS + Modern Glassmorphic Dark CSS served directly by FastAPI `StaticFiles` on port 8000.
- **Architectural Choice**:
  - *Option A*: Retain single-binary/single-process FastAPI serving static assets (zero build step on agency server).
  - *Option B*: Build a separate Next.js / Vite React frontend application connected via REST API / WebSockets.

### Question 2: Handling Disappeared / Resolved Alerts (Accumulative State Engine)
- **Problem**: When a claim is processed on MCMA, MCMA deletes it from the alert queue (`#listeAlerte`). Overwriting the local store deletes past records and employee notes.
- **Proposed Solution**: Implement an **Accumulative Claim Lifecycle Registry**:
  - `ACTIVE`: Currently present on MCMA alert queue.
  - `RESOLVED_ON_MCMA`: Removed by MCMA, but retained in agency local history.
  - Toggle on UI: `[•] Active Queue` vs `[•] Full Agency History & Archive`.

### Question 3: Real-Time Event Push Architecture
- **Problem**: Multiple employees looking at the dashboard need to see status updates, new alerts, and colleague notes without manual page refreshes.
- **Proposed Solution**:
  - *Option A*: **SSE (Server-Sent Events)** streaming from FastAPI (`/api/v1/events/stream`).
  - *Option B*: **WebSocket** full-duplex room server.
  - *Option C*: Lightweight HTTP polling every 5 seconds.

### Question 4: Multi-Account Session Vault & SMS OTP Authentication Flow
- **Problem**: 4 separate accounts requiring SMS OTP authentication when session cookies expire.
- **Proposed Solution**:
  - Multi-session vault (`auth_sessions/mcma_oujda.json`, `auth_sessions/mamda_oujda.json`, etc.).
  - Account Health Indicator bar on header (🟢 Active / 🔴 Expired).
  - In-App `[Se Connecter]` button launching a Playwright window specifically for that account's login + SMS OTP.

---

## 5. Current Implementation Baseline (Verified Capabilities)

- ✅ **Backend Framework**: Python 3.14 + FastAPI + Playwright (Chromium).
- ✅ **Automated Test Suite**: 19/19 passing unit tests (`pytest`).
- ✅ **Notification Extractor**: High-speed AJAX extractor with pagination bypass (`length=-1`).
- ✅ **Web Dashboard**: Dark mode responsive UI with live search, category filtering, KPI metrics, employee action pills, and note modal.
- ✅ **1-Click Launchers**:
  - `DEMARRER_MCMA.bat`: Single master launcher for server & browser.
  - `MCMA_Dashboard_Employe.url`: Desktop shortcut for employee PCs.
  - `Autoriser_Reseau_Local.bat`: Automated Windows Defender Firewall rule for port 8000.

---

## 6. Prompt / Summary for Other LLMs & Architects

> *"We are building an on-premise Operations Hub & RPA Agent for a Moroccan auto insurance agency (MCMA / MAMDA across Oujda and Nador offices). The system connects to `sinauto.mamda-mcma.ma` to monitor notification tables across 4 accounts and automate vehicle expertise form filling from Wexia ERP. We have a working Python FastAPI + Playwright backend with a real-time extraction engine (<2s for 80+ records via in-page AJAX) and a web dashboard. We need to evaluate the best architecture for: (1) Multi-account session vaulting for 4 accounts, (2) Real-time multi-employee UI updates (SSE vs WebSockets), (3) Accumulative claim history retention for alerts deleted by MCMA, and (4) Standalone Frontend (Next.js/React) vs Embedded Single-Server Architecture."*
