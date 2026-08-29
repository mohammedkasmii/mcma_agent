# 🏛️ PROJECT ARCHITECTURE SPECIFICATION & SYSTEM DESIGN BLUEPRINT
**Project:** MCMA / MAMDA Auto Insurance RPA & Operations Hub  
**Target Environment:** Single On-Premise Agency Server (Wexia ERP Ecosystem)  
**Topology:** Single Office LAN (`http://192.168.1.X:8000`)  
**Version:** 3.0 Enterprise Architecture Blueprint  
**Date:** August 2026  

---

## 1. Executive Summary & System Overview

The **MCMA / MAMDA Operations & Automation Hub** is an enterprise RPA engine and operations dashboard designed to monitor incoming claim notifications, track employee work items, and execute automated expertise report filings on the Moroccan insurance portal (`sinauto.mamda-mcma.ma`).

The application is deployed on a **single on-premise local server** in the main agency office (alongside the agency's **Wexia ERP** instance). All agency employees connect to this single server via their local browsers to manage incoming claim queues across all agency accounts.

---

## 2. Multi-Account Scope (4 Portal Accounts)

The system manages **4 separate portal account profiles** operating on the joint `sinauto.mamda-mcma.ma` portal:

| Account ID | Entity | Portfolio / Region | Target Base URL | Primary Role |
|:---|:---:|:---:|:---|:---|
| **`mcma_oujda`** | MCMA | Oujda Dossiers | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |
| **`mamda_oujda`** | MAMDA | Oujda Dossiers | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |
| **`mcma_nador`** | MCMA | Nador Dossiers | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |
| **`mamda_nador`** | MAMDA | Nador Dossiers | `https://sinauto.mamda-mcma.ma/SinAuto_MCMA/` | Notifications + Expertise Filing |

> **Key Domain Reality:** MAMDA and MCMA share the exact same portal web application and DOM structure. The separation into 4 accounts is purely an **account-level login credential & portfolio routing distinction**.

---

## 3. High-Level Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                               AGENCY OFFICE LOCAL NETWORK (LAN)                           │
│                                                                                           │
│     Employee PC 1                 Employee PC 2                 Employee Mobile           │
│     (http://192.168.1.X:8000)     (http://192.168.1.X:8000)     (http://192.168.1.X:8000)   │
└─────────────▲─────────────────────────────▲──────────────────────────────▲────────────────┘
              │                             │                              │
              └─────────────────────────────┼──────────────────────────────┘
                                            │ REST APIs + SSE Stream (/api/v1/events/stream)
                                            ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                       SINGLE ON-PREMISE AGENCY SERVER (FastAPI Engine)                    │
│                                                                                           │
│  ┌─────────────────────────┐   ┌───────────────────────────┐   ┌───────────────────────┐  │
│  │   Vite + React UI       │   │   Background Worker Task  │   │  Form Filling Agent   │  │
│  │  (Compiled Static Dist) │   │   - Account Poller        │   │  (Wexia JSON -> Portal)│  │
│  │  FastAPI Served at /    │   │   - Session Health Check  │   │  - Mode Normal        │  │
│  │                         │   │   - Per-Account Locks     │   │  - Mode Conventionné  │  │
│  └────────────┬────────────┘   └─────────────┬─────────────┘   └───────────┬───────────┘  │
│               │                              │                             │              │
│               └──────────────────────────────┼─────────────────────────────┘              │
│                                              ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                          SQLite Database (WAL Mode)                                 │  │
│  │  Tables: accounts | portal_sessions | claims | employee_actions | audit_events      │  │
│  └───────────────────────────────────────────┬─────────────────────────────────────────┘  │
└──────────────────────────────────────────────┼────────────────────────────────────────────┘
                                               │ Playwright Encrypted Sessions / Chromium
                                               ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                                REMOTE MAMDA / MCMA PORTAL                                 │
│                               (sinauto.mamda-mcma.ma)                                     │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Key Architectural Decisions & Engineering Specifications

### 4.1 Database Layer: SQLite in WAL Mode
- **Decision:** Replace flat JSON files (`claim_registry.json`) with an embedded **SQLite Database in WAL mode (`journal_mode=WAL`)**.
- **Rationale:** Prevents file locking issues, race conditions, and corrupted JSON when 4 background pollers and multiple employees write simultaneously. Provides zero-setup ACID safety.
- **Database Schema Core Tables:**
  - `accounts`: `account_id`, `entity`, `portfolio`, `display_name`, `created_at`
  - `portal_sessions`: `account_id`, `health_status`, `last_validated_at`, `encrypted_auth_state`
  - `claims`: `id`, `reference`, `id_sinistre`, `account_id`, `category_code`, `date_survenance`, `societaire`, `police`, `matricule`, `nature`, `portal_status`, `portal_presence`, `first_seen_at`, `last_seen_at`, `consecutive_missing_polls`
  - `employee_actions`: `reference`, `employee_status` (`TODO`, `IN_PROGRESS`, `DONE`, `WAITING`), `note`, `updated_by`, `updated_at`
  - `audit_events`: `id`, `timestamp`, `event_type`, `user_or_worker`, `details`

---

### 4.2 Dual Lifecycle State Machine (Portal Presence vs. Employee Work Status)
- **Decision:** Strictly separate **Portal Presence** from **Employee Work Status**.
- **Portal Presence States:**
  - 🟢 `ACTIVE`: Present on MCMA/MAMDA alert queue.
  - 🟡 `MISSING_PENDING_CONFIRMATION`: Disappeared in 1st or 2nd poll (guards against temporary network/session drops).
  - ⚪ `RESOLVED_ON_PORTAL`: Absent for 3+ consecutive polls (moved to agency local archive).
- **Employee Work Status:**
  - ⚪ `TODO` *(Unprocessed)*
  - 🔵 `IN_PROGRESS` *(Being handled)*
  - 🟢 `DONE` *(Completed)*
  - 🟡 `WAITING` *(Waiting for external info)*
- **Benefit:** If MCMA removes an alert from its portal queue, the claim is archived locally **without losing employee notes, tags, or work history**.

---

### 4.3 Real-Time Streaming: Server-Sent Events (SSE)
- **Decision:** Use **SSE (`/api/v1/events/stream`)** for real-time server-to-browser notifications.
- **Rationale:** SSE runs over standard HTTP, auto-reconnects natively in JavaScript (`new EventSource()`), requires zero complex broker setup (no Redis/Kafka), and pushes live updates (new alerts, colleague note changes, status updates) instantly to all connected employee screens.

---

### 4.4 Frontend Stack: Vite + React Compiled to Static `dist/`
- **Decision:** Build the user dashboard with **Vite + React + Tailwind/Vanilla CSS**, compile into a single static `dist/` folder, and serve directly from FastAPI via `app.mount("/", StaticFiles(directory="dist", html=True))`.
- **Rationale:** Avoids running a separate Node.js server or Next.js SSR process on the agency server while giving employees a modern, responsive React interface.

---

### 4.5 Execution Architecture & Concurrency Control
- **Decision:** Background job queue with **per-account execution locks (`asyncio.Lock`)**.
- **Execution Flow:**
  - Playwright automation runs asynchronously outside of direct HTTP requests.
  - An `asyncio.Lock()` per `account_id` guarantees that the background notification poller and an employee execution task never attempt to navigate using the same Playwright context simultaneously.

---

### 4.6 Permanent Default-Deny Safety Policy
- **Decision:** Network-level safety interception is a **permanent core system invariant** across all environments.
- **Blocked Endpoints:**
  - `#DEVISDET_Btn` (Final Devis Validation)
  - `#Enregistrer` (Final Mission Save)
  - `cloturerMission` / `validerDevis` / `garageModifierValDevis`
- **Allowed Execution Modes:**
  - `PLAN`: Read and compare DOM values.
  - `PREVIEW`: Populate temporary DOM fields, zero write network requests.
  - `DRAFT_WRITE`: Explicitly authorized row-level checkmarks only.
  - `FINAL_VALIDATION`: **Never available to the agent** (strictly reserved for human experts).

---

## 5. Roadmap & Phased Execution Plan

```
  PHASE 1: Multi-Account Notification & Action Hub (Current Focus)
  ├── 1. SQLite Database Schema Setup (WAL Mode)
  ├── 2. Multi-Account Vault (4 Profile Sessions & Login Manager)
  ├── 3. Sub-Second Extractor & Dual-Lifecycle State Machine
  ├── 4. SSE Real-Time Stream & Vite + React Dashboard UI
  └── 5. Employee Action & Notes Tracking Synchronization

  PHASE 2: Automated Expertise Form Filling Agent (Next Phase)
  ├── 1. Wexia ERP JSON Import & Deterministic Mapper
  ├── 2. Mode Normal Engine (#tableRapportDet)
  ├── 3. Mode Conventionné Engine (#DevisDetTableVal Table 2 Matching)
  └── 4. Human Verification Pause & Safety Audit Logs
```
