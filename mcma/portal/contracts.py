"""
mcma.portal.contracts -- reviewed route contracts and the pure default-deny
decision (INC-07, ADR-0004, SAFETY_MODEL.md §3).

A RouteContract is deliberately narrow: exact host, exact canonical route,
exact method, exact query-field set, exact content type, exact body-field
set. Matching is exact-set equality on both query and body fields -- a
request with one extra or one missing field is a different shape and is
denied, never partially matched. Construction itself is fail-closed:
RouteContract.__post_init__ raises on anything malformed, so a malformed
contract can never enter a policy list and can never allow a request.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from mcma.portal.canonical import SUPPORTED_CONTENT_TYPES, CanonicalRequest
from mcma.portal.final_endpoints import is_permanently_blocked


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class RouteContract:
    host: str
    route: str
    method: str
    query_fields: frozenset[str]
    content_type: str | None
    body_fields: frozenset[str]
    capability: str
    operation_type: str
    workflow: str | None = None

    def __post_init__(self) -> None:
        if not self.host or self.host != self.host.lower():
            raise ValueError(f"RouteContract.host must be a non-empty, lowercase host: {self.host!r}")
        if not self.route.startswith("/"):
            raise ValueError(f"RouteContract.route must be an absolute path: {self.route!r}")
        if self.route != "/" and self.route.endswith("/"):
            raise ValueError(f"RouteContract.route must not end with a trailing slash: {self.route!r}")
        if "//" in self.route or any(seg in (".", "..") for seg in self.route.split("/")):
            raise ValueError(f"RouteContract.route contains an ambiguous/traversal segment: {self.route!r}")
        if not self.method or self.method != self.method.upper():
            raise ValueError(f"RouteContract.method must be non-empty and uppercase: {self.method!r}")
        if self.content_type is not None and self.content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(f"RouteContract.content_type is not supported: {self.content_type!r}")
        if self.content_type is None and self.body_fields:
            raise ValueError("RouteContract.body_fields must be empty when content_type is None")
        if self.method == "GET" and (self.content_type is not None or self.body_fields):
            raise ValueError("RouteContract for GET must not declare a body")
        if not self.capability:
            raise ValueError("RouteContract.capability must be non-empty")
        if not self.operation_type:
            raise ValueError("RouteContract.operation_type must be non-empty")


def contracts_for_workflow(
    workflow: str, contracts: Sequence[RouteContract]
) -> tuple[RouteContract, ...]:
    """The contracts reviewed for this workflow, plus workflow-agnostic
    (shared) ones. Never returns the other workflow's write contracts --
    this is how Mode Normal and PEC policies stay structurally separate."""
    return tuple(c for c in contracts if c.workflow in (workflow, None))


def evaluate_request(
    canonical: CanonicalRequest | None,
    contracts: Sequence[RouteContract],
    allowed_host: str,
) -> Decision:
    if canonical is None:
        return Decision.DENY
    if is_permanently_blocked(canonical.path):
        return Decision.DENY
    if canonical.host != allowed_host:
        return Decision.DENY
    for contract in contracts:
        if (
            contract.host == canonical.host
            and contract.route == canonical.path
            and contract.method == canonical.method
            and contract.query_fields == canonical.query_fields
            and contract.content_type == canonical.content_type
            and contract.body_fields == canonical.body_fields
        ):
            return Decision.ALLOW
    return Decision.DENY
