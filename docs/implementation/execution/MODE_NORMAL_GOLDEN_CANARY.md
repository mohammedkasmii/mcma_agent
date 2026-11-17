# Supervised Mode Normal golden canary

Owner-approved, supervised canary under RELEASE_GATES.md G5 ("explicit owner
approval before the supervised canary"). It is not general production
automation. It is off by default.

## Scope

| In scope | Never |
|---|---|
| Mode Normal (`mission_normal`) only | PEC / Garage Conventionné |
| MCMA Oujda, MCMA Nador | MAMDA (any scope) |
| Rubriques with a confirmed TVA profile: 1, 2, 3, 7, 8, 12, 16, 28 | Any other rubrique, any NeedsReview plan |
| Visible browser on the paired employee workstation | Headless or server-side execution |
| One canary at a time, globally | Concurrent executions |
| Rows + approved header fields + portal-native calculation, then human review | Enregistrer, Valider, Clôture, GED, any final action |
| Charge-split fields read only | Writing `MontantChargeMutuelle` / `MontantChargeSocietaire` |

## Architecture decision

A **separate production adapter**, not a relaxation of the generic writer.

- `mcma/portal/writer.py` (`VerifiedMissionWriter`) is unchanged and keeps
  `_require_loopback_host`, `http://`-only URLs and frozen route contracts.
  Every non-canary EXECUTE still uses it with the loopback pilot contracts.
- `mcma/portal/mode_normal_canary.py` is the canary adapter. It reuses, unchanged:
  - the production `ReadCapability` search/open/identity path (the DRY_RUN one);
  - `verify_identity`, `detect_observed_workflow` and `require_workflow_agreement`;
  - the golden `ModeNormalLiveDriver` primitives from `9a2c57c`, in golden order
    (`#VehRepareI` → Ajouter → `#IdRubrique`/`#MontantHT`/`#Taxe` → column-7
    checkmark), with every primitive's result checked;
  - the golden calculation functions and the rendered-table read-back.
- `mcma/portal/canary_network.py` is the canary-only network policy:
  - The host is pinned to `https://sinauto.mamda-mcma.ma`.
  - Final endpoints and charge-split paths are denied at every moment.
  - Before writing, only the exact search and mission documents plus same-host
    static `script`/`stylesheet`/`image`/`font` GETs are allowed.
  - The portal's own row-save XHR/fetch is allowed only inside a per-row window.
    That window opens immediately before the checkmark click and closes right
    after exact read-back. It allows at most 6 requests in at most 20 s, GET or
    POST only, from the top-level page only.
  - Native calculation gets no window.
  - Any unexpected request, popup, websocket, sub-frame, cross-origin or
    navigation request is a violation, and the run ends in `WRITE_ABORTED`.
- `mcma/planning/canary.py` holds the one plan-eligibility rule. The API
  (creation), the dispatcher (start) and the runner (before the browser opens)
  all apply the same rule.

## The opt-in (server-owned)

`Settings.mode_normal_golden_canary_enabled`, default `false`. Only the central
server reads it, and only at startup. It cannot be set from a request, from the
frontend or from a runner. The runner only follows the `execution_profile` the
server puts on an EXECUTE claim envelope.

### Enable (before the supervised test)

Docker deployment:

1. Add `MCMA_MODE_NORMAL_GOLDEN_CANARY_ENABLED=true` to the env file the
   compose service uses.
2. Restart the service: `docker compose up -d` with the same env file.

Native deployment:

1. Add `mode_normal_golden_canary_enabled = true` to `/etc/mcma/mcma.toml`.
2. Restart the service.

Either way, confirm the log line
`SUPERVISED MODE NORMAL GOLDEN CANARY IS ENABLED` at startup.

### Disable (immediately after)

1. Remove the line, or set it to `false`.
2. Restart the service.
3. Confirm the warning line is gone, and that `POST /jobs/{id}/executions`
   returns `503 RUNNER_CONTROL_PLANE_UNAVAILABLE` again.

Disable only once the canary job is terminal. A job left RUNNING across a
restart with the canary off cannot finish. It then lands on
`INTERRUPTED_NEEDS_HUMAN_REVIEW` when its lease expires, which is fail-closed.

## Preconditions (each enforced in code)

- **Plan:** the workflow is exactly `MODE_NORMAL`. There is no NeedsReview, the
  plan is writeable, and every rubrique is in {1, 2, 3, 7, 8, 12, 16, 28}. This
  is checked by the API, the dispatcher, the runner and the adapter.
- **Account:** the account is `acct-mcma-oujda` or `acct-mcma-nador`, MCMA and
  active. The employee has access to it, and the paired runner belongs to that
  employee and reports a READY session.
- **Parent:** the parent DRY_RUN is `DRY_RUN_VERIFIED` (strict
  reference/idSinistre + registration identity). Identity is re-verified on the
  mission page and before every row.
- **One at a time:** no other EXECUTE dispatch is CLAIMED or RUNNING. This is
  checked inside the claim transaction and re-checked at start.
- **Lease:** the execution lease is valid before and after every row mutation.

## Outcomes

| Outcome | Meaning | Employee action |
|---|---|---|
| `READY_FOR_HUMAN_REVIEW` | Every row read back exactly. Header fields read back. Native calculation ran. Two independent summary reads reconcile TVA and TTC with the plan. | Review the visible browser, then perform the final portal action manually. |
| `WRITE_ABORTED` | Any mismatch, violation, cancellation, lease loss or browser close. | The browser stays open (all network blocked) for up to 30 min. Inspect what was written and correct it manually. |
| `IDENTITY_FAILED` | Search, identity or workflow failed before any mutation. | None. Nothing was written. |

## Evidence

The runner writes one JSON file per run to
`%LOCALAPPDATA%\MCMA Runner\canary_evidence\`. It contains:

- the outcome, a fixed reason code and the number of rows written;
- one record per request: phase, row index, method, normalized path (numeric
  and opaque identifier segments replaced, query dropped), resource type, decision, reason, relative
  time, HTTP status, and body field NAMES plus a hash of those names.

It never contains values, cookies, credentials, claimant data or raw bodies.
The `ROW_WINDOW` records are the input for the next increment's exact
row-save contract.
