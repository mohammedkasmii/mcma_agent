"""
mcma.portal.canonical -- pure request canonicalization (INC-07, ADR-0004,
SAFETY_MODEL.md §3). No Playwright dependency; no I/O.

Ambiguous input never gets a best-effort guess: canonicalize_request()
returns None on anything malformed or ambiguous (userinfo, unparseable
host/port, non-absolute path, encoded/duplicate path separators, path
traversal, duplicate query or body field names, unsupported content type, a
body-parsing failure, or a GET carrying a body). Callers (mcma.portal.
contracts.evaluate_request) treat None as an unconditional deny.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

SUPPORTED_CONTENT_TYPES = ("application/x-www-form-urlencoded", "application/json")

_SUSPICIOUS_PATH_MARKERS = ("%2e", "%2f", "%5c", "%00", "\\")


@dataclass(frozen=True)
class CanonicalRequest:
    """One unambiguous request shape. `path` excludes query/fragment, has no
    trailing slash (except the root "/"), and is free of duplicate
    separators, encoded separators, and traversal segments."""

    host: str
    path: str
    method: str
    query_fields: frozenset[str]
    content_type: str | None
    body_fields: frozenset[str]


def _normalize_content_type(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.split(";", 1)[0].strip().lower()
    return value or None


def _path_is_suspicious(raw_path: str) -> bool:
    lowered = raw_path.lower()
    if any(marker in lowered for marker in _SUSPICIOUS_PATH_MARKERS):
        return True
    if "//" in raw_path:
        return True
    if any(segment in (".", "..") for segment in raw_path.split("/")):
        return True
    return False


def _canonical_path(raw_path: str) -> str | None:
    if not raw_path.startswith("/"):
        return None
    if _path_is_suspicious(raw_path):
        return None
    if raw_path != "/" and raw_path.endswith("/"):
        raw_path = raw_path[:-1]
    return raw_path


def _field_set_no_duplicates(pairs: list[tuple[str, str]]) -> frozenset[str] | None:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        return None
    return frozenset(keys)


def _query_fields(raw_query: str) -> frozenset[str] | None:
    pairs = parse_qsl(raw_query, keep_blank_values=True, strict_parsing=False)
    return _field_set_no_duplicates(pairs)


def _body_fields(content_type: str | None, raw_body: str | None) -> frozenset[str] | None:
    if content_type is None:
        return None if raw_body else frozenset()
    if content_type == "application/x-www-form-urlencoded":
        pairs = parse_qsl(raw_body or "", keep_blank_values=True, strict_parsing=False)
        return _field_set_no_duplicates(pairs)
    if content_type == "application/json":
        try:
            parsed = json.loads(raw_body) if raw_body else None
        except (ValueError, TypeError):
            return None
        if not isinstance(parsed, dict):
            return None
        return frozenset(parsed.keys())
    return None  # unreachable: content_type is validated as supported before this call


def canonicalize_request(
    *,
    raw_url: str,
    raw_method: str,
    raw_content_type: str | None,
    raw_body: str | None,
) -> CanonicalRequest | None:
    if not raw_method:
        return None
    method = raw_method.upper()

    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return None

    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None

    hostname = parsed.hostname
    if not hostname:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    host = hostname.lower() if port is None else f"{hostname.lower()}:{port}"

    path = _canonical_path(parsed.path)
    if path is None:
        return None

    query_fields = _query_fields(parsed.query)
    if query_fields is None:
        return None

    content_type = _normalize_content_type(raw_content_type)
    if content_type is not None and content_type not in SUPPORTED_CONTENT_TYPES:
        return None

    body_fields = _body_fields(content_type, raw_body)
    if body_fields is None:
        return None

    if method == "GET" and (content_type is not None or body_fields or raw_body):
        return None

    return CanonicalRequest(
        host=host,
        path=path,
        method=method,
        query_fields=query_fields,
        content_type=content_type,
        body_fields=body_fields,
    )
