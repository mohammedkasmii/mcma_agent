"""
Pilot-integration correction (sections 3/4) -- shared fixtures/constants
for tests/execution/runner/*. Deliberately self-contained (its own
uvicorn mock-server bootstrap, its own contract/typed-input literals)
rather than importing tests/portal/writer/writer_live_chromium_test_
support.py or tests/portal/capabilities/capabilities_test_support.py --
the established INC-06/07/08/09 convention: a bare cross-directory import
of a same-purpose module is the exact fragility already fixed once
(collision when the whole suite runs together / import order is
directory-name-dependent). A little duplication here is the safe
trade-off; see tests/portal/capabilities/test_live_chromium_proof.py for
the same pattern used for the identical reason.
"""

import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

import mock_server
from mcma.app.provisioning import ensure_canonical_accounts
from mcma.domain.portal_accounts import (
    PortalAccountProfile,
    PortalEntity,
    PortalScope,
    canonical_account_id,
)
from mcma.execution.inputs import TestOnlyPlaintextEncryptor
from mcma.persistence.db import open_database
from mcma.persistence.leases import acquire_lease
from mcma.portal.vault import TestOnlyAclVerifier, TestOnlyInMemoryCryptoBackend, store_session

ALLOWED_HOST = "127.0.0.1:8080"
PROOF_HOST, _proof_port_str = ALLOWED_HOST.split(":", 1)
PROOF_PORT = int(_proof_port_str)
BASE_URL = f"http://{ALLOWED_HOST}"

MCMA_OUJDA_ACCOUNT_ID = canonical_account_id(PortalAccountProfile(PortalEntity.MCMA, PortalScope.OUJDA))
INSTANCE_ID = "runner-test-instance"

# The mock's two synthetic missions (mock_server.py's own seeded state,
# already proven against by every tests/portal/writer/*_live_chromium_
# proof.py test): Mode Normal (matricule 77001-C-3) and Garage
# Conventionne/PEC (matricule 34602-B-7), each with a distinct
# #IdSinistre__I DOM value the writer tests already verify against.
MODE_NORMAL_TYPED_INPUT = {
    "dossier": {
        "id_sinistre": "699001",
        "mission_type": "normal",
        "incident_description": "MODE NORMAL",
        "is_reform": False,
    },
    "vehicule": {"license_plate": "77001-C-3"},
    "chiffrages": [
        {
            "id": "CH-NORMAL-1",
            "status": "approved",
            "is_final": True,
            "scenario_type": "repair",
            "total_cost": 10,
            "tax_amount": 2,
            "lignes_pieces": [
                {"item_type": "part", "item_name": "pare-choc avant", "part_type": "original", "subtotal": 10}
            ],
        }
    ],
}

PEC_TYPED_INPUT = {
    "dossier": {
        "id_sinistre": "534660",
        "mission_type": "garage conventionne",
        "is_reform": False,
    },
    "vehicule": {"license_plate": "34602-B-7"},
    "chiffrages": [
        {
            "id": "CH-PEC-1",
            "status": "approved",
            "is_final": True,
            "scenario_type": "repair",
            "total_cost": 10,
            "tax_amount": 2,
            "lignes_pieces": [
                {"item_type": "part", "item_name": "pare-choc avant", "part_type": "used", "subtotal": 10}
            ],
        }
    ],
}


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture()
def conn(tmp_path: Path):
    connection = open_database(tmp_path / "mcma_runner_test.sqlite3")
    ensure_canonical_accounts(connection)
    connection.execute(
        "INSERT INTO users (user_id, username, password_hash, role, active) "
        "VALUES ('operator-1', 'operator-1', 'hash', 'operator', 1)"
    )
    yield connection
    connection.close()


@pytest.fixture()
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d


@pytest.fixture()
def encryptor() -> TestOnlyPlaintextEncryptor:
    return TestOnlyPlaintextEncryptor()


@pytest.fixture()
def crypto_backend() -> TestOnlyInMemoryCryptoBackend:
    return TestOnlyInMemoryCryptoBackend()


def enqueue_dry_run_job(conn, encryptor, *, typed_input: dict, key: str) -> str:
    import json

    from mcma.execution.inputs import compute_content_hash
    from mcma.execution.jobs import enqueue_dry_run
    from mcma.mapping.wexia import parse_wexia
    from mcma.planning.plan import detect_workflow
    from mcma.planning.registry import workflow_name_for

    parsed = parse_wexia(typed_input)
    workflow_name = workflow_name_for(detect_workflow(parsed))
    typed_input_bytes = json.dumps(typed_input, sort_keys=True).encode("utf-8")
    return enqueue_dry_run(
        conn,
        account_id=MCMA_OUJDA_ACCOUNT_ID,
        requested_by_user_id="operator-1",
        workflow_name=workflow_name,
        input_hash=compute_content_hash(typed_input_bytes),
        typed_input_bytes=typed_input_bytes,
        idempotency_key=key,
        encryptor=encryptor,
    )


def seed_mcma_oujda_session(conn, vault_dir: Path, crypto_backend) -> None:
    """The mock never checks cookies (every existing writer-tests proof
    opens without context_options at all) -- this stores a minimal, valid
    storage_state purely so load_and_verify_session() has a real ACTIVE
    row/file to load, exactly mirroring production's own shape."""
    lease = acquire_lease(conn, MCMA_OUJDA_ACCOUNT_ID, INSTANCE_ID)
    try:
        storage_state = b'{"cookies": [], "origins": []}'
        store_session(
            conn, lease, MCMA_OUJDA_ACCOUNT_ID, storage_state,
            vault_dir=vault_dir, backend=crypto_backend, acl_verifier=TestOnlyAclVerifier(True),
        )
    finally:
        lease.release()


class _ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        super().__init__(daemon=True)
        self._config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self._server = uvicorn.Server(self._config)

    def run(self):
        asyncio.run(self._server.serve())

    def stop(self):
        self._server.should_exit = True


@pytest.fixture()
def live_mock_server():
    mock_server.MOCK_STATE.clear()
    mock_server.MOCK_STATE.update(mock_server._initial_state())
    thread = _ServerThread(mock_server.app, PROOF_HOST, PROOF_PORT)
    thread.start()
    for _ in range(50):
        try:
            with socket.create_connection((PROOF_HOST, PROOF_PORT), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:  # pragma: no cover - defensive
        raise RuntimeError("live mock server did not start in time")
    try:
        yield BASE_URL
    finally:
        thread.stop()
        thread.join(timeout=5)
        mock_server.MOCK_STATE.clear()
        mock_server.MOCK_STATE.update(mock_server._initial_state())
