"""
mcma.app.serve -- TLS bootstrap (INC-18, ADR-0008, API_CONTRACTS.md §1).

Serves HTTPS only. There is NO plaintext HTTP listener anywhere in this
module -- not even an HTTP->HTTPS redirect (API_CONTRACTS.md §1 / review
AR-L4: a redirect listener is deliberately out of scope here, smaller
attack surface; an external reverse proxy is where one would live if it
were ever needed). Every path that starts a real server goes through
build_ssl_context()/build_uvicorn_ssl_kwargs() first -- both fail closed
(TlsConfigurationError) on any certificate problem, and NEITHER has a
fallback that returns plaintext-serving kwargs. `subnet_allowlist` is
strictly defense-in-depth (ADR-0008): empty (the default) means every
request is passed through completely unfiltered by this module --
authentication (mcma.app.api) is what actually protects every
account-scoped route, with or without a subnet filter configured.

Dev-mode loopback TLS (a self-signed dev cert, `host="127.0.0.1"`) and
production TLS (the internal-CA-issued cert, deploy/tls/README.md) both
go through the exact same TlsConfig/build_ssl_context path -- the only
difference is which cert/key files and which host a caller supplies;
there is no separate "dev bypasses TLS" code path to accidentally reuse
in production.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Sequence


class TlsConfigurationError(Exception):
    """The service cannot start over TLS -- missing/unreadable/corrupt
    cert or key, or a cert/key mismatch. There is no fallback: raising
    this is always the end of the attempt to serve, never a signal to
    retry over plain HTTP."""


@dataclass(frozen=True)
class TlsConfig:
    cert_path: Path
    key_path: Path
    host: str = "0.0.0.0"
    port: int = 8443
    # Defense-in-depth ONLY (ADR-0008) -- e.g. ("192.168.1.0/24",). Empty
    # by default; never required for authentication to function correctly.
    subnet_allowlist: tuple = ()


def build_ssl_context(config: TlsConfig) -> ssl.SSLContext:
    """Fails closed on every certificate problem -- missing files, an
    unreadable/corrupt cert or key, or a cert/key mismatch all raise
    TlsConfigurationError. Never returns a context for an invalid pair,
    and never silently proceeds without one."""
    cert_path = Path(config.cert_path)
    key_path = Path(config.key_path)
    if not cert_path.is_file():
        raise TlsConfigurationError(f"TLS certificate not found: {cert_path}")
    if not key_path.is_file():
        raise TlsConfigurationError(f"TLS private key not found: {key_path}")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    except ssl.SSLError as exc:
        raise TlsConfigurationError(f"invalid or mismatched certificate/key: {exc}") from exc
    except OSError as exc:
        raise TlsConfigurationError(f"could not read certificate/key: {exc}") from exc
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def build_uvicorn_ssl_kwargs(config: TlsConfig) -> dict:
    """The ONLY kwargs this module ever produces for actually starting a
    server. Validates the cert/key first (raising TlsConfigurationError,
    never returning) -- there is no sibling function anywhere in this
    module that returns HTTP-only server kwargs."""
    build_ssl_context(config)
    return {"ssl_certfile": str(config.cert_path), "ssl_keyfile": str(config.key_path)}


class SubnetAllowlistMiddleware:
    """Defense-in-depth ONLY. An empty allowlist means this middleware is
    never even constructed (see wrap_with_subnet_allowlist) -- when it
    IS configured, it can only additionally REJECT a request; it never
    grants access an authenticated caller would not already have, and a
    request it allows through still has to pass mcma.app.api's own
    authentication/authorization exactly as if this middleware did not
    exist."""

    def __init__(self, app, subnet_allowlist: Sequence[str]) -> None:
        self._app = app
        self._networks = tuple(ip_network(cidr) for cidr in subnet_allowlist)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not self._networks:
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        if client is None or not any(ip_address(client[0]) in network for network in self._networks):
            await send(
                {"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json")]}
            )
            await send({"type": "http.response.body", "body": b'{"error":"SUBNET_NOT_ALLOWED"}'})
            return
        await self._app(scope, receive, send)


def wrap_with_subnet_allowlist(app, subnet_allowlist: Sequence[str]):
    """Returns `app` UNCHANGED when subnet_allowlist is empty (the
    default) -- proving the absence of a subnet filter is a genuine
    no-op, never an implicit "allow everything" gate that could be
    confused with an authentication check."""
    if not subnet_allowlist:
        return app
    return SubnetAllowlistMiddleware(app, subnet_allowlist)


def serve(app, config: TlsConfig) -> None:  # pragma: no cover - real server loop, not unit-testable
    import uvicorn

    wrapped = wrap_with_subnet_allowlist(app, config.subnet_allowlist)
    ssl_kwargs = build_uvicorn_ssl_kwargs(config)
    uvicorn.run(wrapped, host=config.host, port=config.port, **ssl_kwargs)
