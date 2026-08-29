# Release Gates (safety gates that block progression)

A gate is a hard stop: the next phase does not begin until the gate's evidence is produced and reviewed. Gates are
fail-closed — absence of evidence blocks progression.

| Gate | After | Blocks | Evidence required |
|---|---|---|---|
| **G0** Egress lockdown | INC-01 | any browser test/code (INC-06+) | subprocess + Chromium proof tests green; OS/CI egress denial enforced |
| **G1** Pure deterministic fail-closed core | INC-05 | Phase 2 | import-linter green; `plan_hash` determinism; every unknown/ambiguous domain case fails closed |
| **G2** Write-safety core (no live writes) | INC-09 | Phase 3 | dry-run has no writer; final endpoints abort; unknown requests fail closed; identity + exact-IdRubrique fail closed; charge-mutuelle never written — all against the mock; live writes still disabled |
| **G3** Durable orchestration | INC-13 | Phase 4 | deterministic crash-recovery; OS mutex + lease single-writer; vault fails closed on decrypt/binding failure |
| **G4** Authenticated TLS API | INC-18 | Phase 6 | TLS-only (refuse without cert); per-account authorized API; server-derived audit |
| **G-PDR** Production-data-readiness | INC-20 + INC-21 | **any persistence of real production PII** (notifications/sessions/claims) | DB outside served directories; BitLocker **or** SQLCipher condition satisfied; strict NTFS ACL verified; encrypted backup destination verified; PII-safe logging **and** screenshot behavior verified. No production PII is stored before this gate — INC-14 stays fixture/mock-only until it passes. |
| **G5** Live-write gate | INC-23 | any live row write | confirmed row-op contracts from approved evidence; full safety suite green; write-enable gate satisfied; final endpoints still blocked; **explicit owner approval** before the supervised canary |

## Standing prohibitions (apply throughout, not just at a gate)
- **No live form filling** until G5 passes with owner approval. Endpoint names in the baseline never authorize writes.
- **Baseline containment (INC-00, from day one):** the baseline's own live-write entrypoints (`fill-dossier`,
  `process_workflow`, Mode-Normal forced charge-mutuelle) are structurally disabled and its API is bound to loopback with
  the `profile=any` firewall rule removed, for the entire rebuild. The "no live form filling" prohibition binds the
  baseline, not only the new stack.
- **No test contacts the live portal** at any point (G0 enforces this authoritatively via OS/CI egress denial).
- **Human final validation is mandatory** — the agent never invokes Enregistrer/Valider/Clôture/GED; a job ends at
  `READY_FOR_HUMAN_REVIEW`; `FINALIZED_BY_HUMAN` is an observed business event only.
- **Fail-closed everywhere** — any ambiguity in mapping, identity, tax, rubrique selection, session decryption, or
  crash-recovery resolves to a non-writing, reviewable state.

## Per-increment gate participation
G0: INC-01. G1: INC-03,04,05. G2: INC-06,07,08,09. G3: INC-10,11,12,13. G4: INC-16,17,18 (INC-19,20,21 are quality gates,
not blocking safety gates). G5: INC-23 (with INC-09/12/13/18/22 as prerequisites).
