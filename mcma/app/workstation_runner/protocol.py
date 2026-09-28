"""mcma.app.workstation_runner.protocol -- wire-protocol constants for the
central runner registry (mcma/app/api/runners.py + mcma/app/runners/registry.py).

Deliberately duplicated as literals rather than imported from
mcma.app.runners.registry: that module pulls in mcma.app.auth.* (which may
reach fastapi / mcma.persistence), which would break this package's
"imports no server/FastAPI/SQLite code" isolation (see
tests/app/workstation_runner/test_import_isolation.py). Keep these values
byte-for-byte identical to the server's; a mismatch is a protocol bug."""

from __future__ import annotations

PROTOCOL_VERSION = 1
APP_VERSION = "1.0.0"  # must match ^[0-9A-Za-z][0-9A-Za-z.+-]{0,31}$

# mirrors mcma.app.runners.registry.RUNNER_ACCOUNT_IDS
RUNNER_ACCOUNT_IDS = ("acct-mcma-oujda", "acct-mcma-nador")

# mirrors mcma.app.runners.registry.SESSION_STATES. Phase 1B-A sends no
# sessions at all (see http_client.heartbeat's `sessions` default of ()) --
# there are no browser sessions yet to report -- but the closed enum is
# already here so a later phase reporting real session state does not need
# a second round of protocol duplication.
SESSION_STATES = ("NOT_CONFIGURED", "LOGIN_REQUIRED", "READY", "ERROR")
SESSION_STATE_NOT_CONFIGURED = "NOT_CONFIGURED"

# mirrors mcma.app.runners.registry.RUNNER_SECRET_PREFIX / MAX_RUNNER_SECRET_LENGTH
RUNNER_SECRET_PREFIX = "mcma_rs_"
MAX_RUNNER_SECRET_LENGTH = 200

# sane bounds for server-provided scheduling values -- never trust the
# network to hand us 0, a negative number, or something absurdly large
MIN_HEARTBEAT_INTERVAL_SECONDS = 1
MAX_HEARTBEAT_INTERVAL_SECONDS = 3600
MIN_OFFLINE_AFTER_SECONDS = 1
MAX_OFFLINE_AFTER_SECONDS = 7200

# mirrors mcma.app.runners.dispatch.CLAIM_TOKEN_PREFIX / MAX_CLAIM_TOKEN_LENGTH
# (Phase 1C-A: durable job-dispatch claim/renew/release). No job dispatch
# is actually PERFORMED by this lightweight package yet -- only the wire
# constants needed to validate a server response are duplicated here.
CLAIM_TOKEN_PREFIX = "mcma_ct_"
MAX_CLAIM_TOKEN_LENGTH = 200

# mirrors mcma.app.runners.dispatch's fixed release reason set.
RELEASE_REASONS = ("CANCELLED_BEFORE_EXECUTION", "RUNNER_SHUTDOWN", "EXECUTION_NOT_AVAILABLE")

# mirrors mcma.execution.jobs' mode literals -- the only two a claimed job
# envelope may ever report.
JOB_MODES = ("DRY_RUN", "EXECUTE")

# mirrors mcma.app.runners.dispatch.FINISH_RESULTS (Phase 1C-B: the fixed,
# closed enum /runner/jobs/{job_id}/finish accepts -- never arbitrary
# client status/error text).
FINISH_RESULTS = (
    "IDENTITY_MATCHED", "IDENTITY_NOT_MATCHED", "SESSION_UNAVAILABLE", "PORTAL_READ_FAILED", "RUNNER_CANCELLED",
)

# mirrors mcma.app.runners.dispatch.MAX_CLAIM_RESPONSE_BYTES / MAX_TYPED_INPUT_DEPTH
# (P1 correction: the server now enforces these SAME bounds before a claim
# row is ever inserted, not just this client on receipt -- see dispatch.py's
# own module-level comment. http_client.py imports these from here rather
# than defining its own copy, so there is exactly one client-side literal to
# keep byte-for-byte identical to the server's.)
MAX_CLAIM_RESPONSE_BYTES = 262_144  # 256 KiB
MAX_TYPED_INPUT_DEPTH = 16
