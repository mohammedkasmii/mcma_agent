"""The 4096-byte runner-API body limit is enforced WHILE STREAMING: an
oversized body is refused as soon as the limit is crossed and the rest of the
stream is never read. Driven at the ASGI level (a Request with a scripted
`receive`) so chunk consumption can be observed exactly."""

import asyncio
import json
import logging

import pytest
from starlette.requests import Request

from mcma.app.api.errors import ApiError
from mcma.app.api.runners import MAX_BODY_BYTES, _bounded_json, _read_bounded


class Stream:
    """A scripted request body that counts how many chunks were pulled."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.pulled = 0

    async def receive(self):
        if self.pulled >= len(self.chunks):
            return {"type": "http.request", "body": b"", "more_body": False}
        chunk = self.chunks[self.pulled]
        self.pulled += 1
        return {"type": "http.request", "body": chunk, "more_body": self.pulled < len(self.chunks)}


def _request(chunks, content_length="absent"):
    stream = Stream(chunks)
    headers = [(b"content-type", b"application/json")]
    if content_length != "absent":
        headers.append((b"content-length", str(content_length).encode()))
    scope = {"type": "http", "method": "POST", "path": "/runner/enroll", "headers": headers, "query_string": b""}
    return Request(scope, stream.receive), stream


def _run(coro):
    return asyncio.run(coro)


def _refusal(coro):
    with pytest.raises(ApiError) as info:
        _run(coro)
    return info.value


def _json_of_size(size):
    """A JSON object of EXACTLY `size` bytes."""
    overhead = len(json.dumps({"pad": ""}).encode())
    return json.dumps({"pad": "x" * (size - overhead)}).encode()


ALLOWED = {"pad"}


def test_an_oversized_streamed_body_with_no_content_length_is_refused_and_reading_stops():
    chunks = [b"x" * 1024] * 400                                   # 400 KB offered
    request, stream = _request(chunks)
    error = _refusal(_bounded_json(request, ALLOWED, set()))
    assert (error.status_code, error.code, error.message) == (413, "PAYLOAD_TOO_LARGE", "corps trop volumineux")
    assert stream.pulled == 5                                       # 5 x 1024 > 4096: stopped there ...
    assert stream.pulled < len(chunks)                              # ... not after draining the rest


def test_a_falsely_small_content_length_does_not_fool_the_limit():
    chunks = [b"y" * 2048] * 100
    request, stream = _request(chunks, content_length=10)
    error = _refusal(_bounded_json(request, ALLOWED, set()))
    assert error.status_code == 413 and stream.pulled == 3          # 3 x 2048 > 4096
    assert stream.pulled < len(chunks)


def test_an_oversized_declared_content_length_is_refused_without_reading_the_body():
    request, stream = _request([b"{}"], content_length=MAX_BODY_BYTES + 1)
    assert _refusal(_bounded_json(request, ALLOWED, set())).status_code == 413
    assert stream.pulled == 0                                       # never touched the stream


@pytest.mark.parametrize("declared", ["abc", "-5", "1e9", "", " 12", "99999999999999999999"])
def test_a_malformed_or_absurd_content_length_is_refused_immediately(declared):
    request, stream = _request([b"{}"], content_length=declared)
    assert _refusal(_bounded_json(request, ALLOWED, set())).status_code == 413
    assert stream.pulled == 0


def test_the_exact_boundary_is_accepted_and_one_byte_more_is_not():
    exact = _json_of_size(MAX_BODY_BYTES)
    assert len(exact) == MAX_BODY_BYTES
    request, _ = _request([exact], content_length=len(exact))
    assert _run(_bounded_json(request, ALLOWED, set()))["pad"].startswith("x")
    over = _json_of_size(MAX_BODY_BYTES + 1)
    request, stream = _request([over], content_length=len(over))
    assert _refusal(_bounded_json(request, ALLOWED, set())).status_code == 413
    # The same boundary without a declaration, split across many small chunks.
    pieces = [exact[i:i + 100] for i in range(0, len(exact), 100)]
    request, stream = _request(pieces)
    assert _run(_bounded_json(request, ALLOWED, set()))["pad"] and stream.pulled == len(pieces)
    pieces = [over[i:i + 100] for i in range(0, len(over), 100)]
    request, stream = _request(pieces)
    assert _refusal(_bounded_json(request, ALLOWED, set())).status_code == 413
    assert stream.pulled == len(pieces)                             # crossed on the very last chunk


def test_a_valid_small_body_split_across_chunks_is_assembled_and_parsed():
    body = json.dumps({"pad": "hello"}).encode()
    request, _ = _request([body[:5], body[5:9], body[9:]], content_length=len(body))
    assert _run(_bounded_json(request, ALLOWED, set())) == {"pad": "hello"}


@pytest.mark.parametrize("raw", [b"{not json", b"", b"\xff\xfe\x00", b"nul", b'{"pad": '])
def test_invalid_json_is_a_fixed_bad_request_that_never_echoes(raw):
    request, _ = _request([raw], content_length=len(raw))
    error = _refusal(_bounded_json(request, ALLOWED, set()))
    assert (error.status_code, error.code, error.message) == (400, "BAD_REQUEST", "corps JSON invalide")


@pytest.mark.parametrize("raw, message", [
    (b"[1, 2]", "un objet JSON est attendu"), (b'"text"', "un objet JSON est attendu"), (b"5", "un objet JSON est attendu"),
    (b'{"pad": 1, "extra": 2}', "champs invalides"), (b"{}", "champs invalides"),
])
def test_strict_object_and_field_validation_is_preserved(raw, message):
    request, _ = _request([raw])
    required = {"pad"} if raw == b"{}" else set()
    error = _refusal(_bounded_json(request, ALLOWED, required))
    assert error.status_code == 400 and error.message == message
    assert "extra" not in error.message


def test_errors_and_logs_never_contain_the_body(caplog):
    caplog.set_level(logging.DEBUG)
    secret = "mcma_pc_" + "S3CRET" * 8
    payload = json.dumps({"pairing_code": secret, "pad": "x" * 6000}).encode()
    request, _ = _request([payload[:2000], payload[2000:4000], payload[4000:]])
    error = _refusal(_bounded_json(request, ALLOWED, set()))
    assert secret not in error.message and secret not in error.code and secret not in caplog.text
    bad = b'{"pairing_code": "' + secret.encode() + b'", '
    request, _ = _request([bad])
    error = _refusal(_bounded_json(request, ALLOWED, set()))
    assert secret not in error.message and secret not in caplog.text


def test_read_bounded_never_holds_more_than_the_limit_plus_one_chunk():
    """Accepted bytes are appended only while within the limit, so the
    accumulated list can never exceed MAX_BODY_BYTES."""
    chunk = b"z" * 1000
    request, stream = _request([chunk] * 50)
    _refusal(_read_bounded(request))
    assert (stream.pulled - 1) * len(chunk) <= MAX_BODY_BYTES < stream.pulled * len(chunk)


# ------------------ through the real endpoints (declared sizes, real server path) ------------------ #


def test_the_real_endpoints_answer_413_for_oversized_bodies_and_stay_generic():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from fastapi.testclient import TestClient

    from api_test_support import conn as _unused  # noqa: F401
    from mcma.app.api.app import create_api_app
    from mcma.app.auth.provider import LocalUserAuthProvider
    from mcma.app.auth.sessions import SessionStore
    from mcma.execution.inputs import TestOnlyPlaintextEncryptor
    from mcma.persistence.db import open_database
    import tempfile

    connection = open_database(Path(tempfile.mkdtemp()) / "b.sqlite3")
    app = create_api_app(connection, auth_provider=LocalUserAuthProvider(connection), session_store=SessionStore(),
                         encryptor=TestOnlyPlaintextEncryptor(), secure_cookies=True, runner_registry=True)
    client = TestClient(app, base_url="https://testserver")
    huge = {"pairing_code": "x" * 10_000, "protocol_version": 1, "app_version": "1"}
    response = client.post("/runner/enroll", json=huge)
    assert response.status_code == 413 and response.json()["error"] == "PAYLOAD_TOO_LARGE"
    assert "xxxx" not in response.text
    chunked = client.post("/runner/enroll", content=(b"x" * 1000 for _ in range(20)),
                          headers={"Content-Type": "application/json"})            # no Content-Length at all
    assert chunked.status_code == 413
    ok = client.post("/runner/enroll", json={"pairing_code": "mcma_pc_" + "A" * 43, "protocol_version": 1, "app_version": "1"})
    assert ok.status_code == 400 and ok.json()["error"] == "PAIRING_CODE_INVALID"      # a normal body still works
    connection.close()
