# Architecture Decision Records

Baseline (production code): `0290fe9df24c9e2f2b054ee4f8b14b8267f07b12`. These ADRs record the Phase 3 decisions for the
MCMA rebuild target architecture. Status of all: **Accepted (design)** — implemented incrementally in later phases.

| ADR | Title |
|---|---|
| [0001](0001-modular-monolith.md) | Incremental modular monolith over service decomposition |
| [0002](0002-deterministic-workflow-planning.md) | Deterministic workflow planning with typed execution plans |
| [0003](0003-read-write-capability-separation.md) | Read/write capability separation; write-incapable dry-run |
| [0004](0004-network-default-deny.md) | Context-level default-deny interception; permanent final-endpoint block |
| [0005](0005-sqlite-wal-outbox.md) | SQLite WAL + transactional outbox; at-rest protection |
| [0006](0006-claim-identity-presence.md) | Claim identity (account_id + idSinistre) & category-presence history |
| [0007](0007-multi-account-session-vault.md) | Multi-account session vault; leases; DPAPI |
| [0008](0008-api-auth-authz.md) | API authentication/authorization; TLS; configurable LAN exposure |
| [0009](0009-sse-delta-recovery.md) | SSE + delta recovery via outbox + monotonic versions |
| [0010](0010-incremental-migration.md) | Incremental migration strategy |
