import asyncio
import json
import re
import hashlib
from collections import deque
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, parse_qsl, urlunparse

from playwright.async_api import async_playwright

try:
    import tldextract
except ImportError:
    tldextract = None


# ============================================================
# CONFIG
# ============================================================

OUTPUT_DIR = Path("website_investigation_v6")
# Cumulative store: NOT timestamped, persists across runs so you can capture
# the same workflow 2-3 times (different dropdown choices, different branch
# of a conditional form, etc.) and build up one trustworthy schema instead
# of overwriting it each time.
CUMULATIVE_DIR = Path("website_investigation_cumulative")

MAX_BODY_BYTES = 2_000_000
MAX_RESPONSE_TEXT = 5000
CLICK_CORRELATION_WINDOW_SECONDS = 5.0
MUTATION_DEBOUNCE_MS = 700
MAX_OPTIONS_PER_SELECT = 300   # cap so a "select client" dropdown with
                                 # thousands of entries doesn't blow up output
MIN_VALUE_LEN_FOR_TRACKING = 3
MAX_VALUE_LEN_FOR_TRACKING = 200
MAX_VALUE_LINKS = 300

INFRA_PATH_PARTS = {
    "/socket.io/", "/sockjs/", "/signalr/", "/hot-update/", "/__webpack_hmr",
    "/_next/webpack-hmr", "/vite-hmr", "/browser-sync/", "/__vite_ping",
    "/telemetry", "/metrics", "/analytics", "/collect",
}

INFRA_HOST_PARTS = {
    "google-analytics.com", "googletagmanager.com", "doubleclick.net",
    "googlesyndication.com", "facebook.net", "facebook.com", "segment.io",
    "hotjar.com", "sentry.io", "fundingchoicesmessages.google.com",
    "adtrafficquality.google", "www.google.com",
}

STATIC_EXTENSIONS = {
    ".js", ".mjs", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg",
    ".ico", ".webp", ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4",
    ".webm", ".avi", ".mov", ".pdf", ".zip", ".gz", ".map", ".wasm",
}

SENSITIVE_HEADERS = {
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "x-access-token", "x-refresh-token",
}

SENSITIVE_KEYWORDS = {
    "password", "passwd", "pwd", "token", "access_token", "refresh_token",
    "authorization", "cookie", "secret", "api_key", "apikey", "client_secret",
    "session", "csrf", "xsrf",
}


# ============================================================
# HELPERS — redaction / formatting
# ============================================================

def now():
    return datetime.now().isoformat(timespec="seconds")


def redact_string(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b", "[REDACTED_JWT]", value)
    value = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9._~+/=-]{16,}", r"\1[REDACTED]", value)
    return value


def redact_object(value):
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if any(word in str(key).lower() for word in SENSITIVE_KEYWORDS):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_object(val)
        return out
    if isinstance(value, list):
        return [redact_object(v) for v in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


def redact_headers(headers):
    return {
        key: "[REDACTED]" if key.lower() in SENSITIVE_HEADERS else redact_string(value)
        for key, value in headers.items()
    }


def describe_format(value):
    """Describes the SHAPE of a value (length + character pattern) without
    exposing it. Enough for an agent to know 'this is a 64-char hex token
    you must re-fetch fresh each session' without ever seeing the token."""
    if not isinstance(value, str):
        return {"length": None, "format": "non-string"}
    length = len(value)
    if re.fullmatch(r"[0-9a-fA-F]{16,}", value):
        fmt = "hex"
    elif re.fullmatch(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{10,}", value):
        fmt = "jwt-like"
    elif re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value):
        fmt = "uuid-like"
    elif re.fullmatch(r"[A-Za-z0-9+/=_-]{16,}", value):
        fmt = "base64-or-token-like"
    else:
        fmt = "opaque-string"
    return {"length": length, "format": fmt}


def classify_hidden_value(name, value):
    """Decides whether a hidden/default field value is safe to record as-is,
    or should be redacted with a format hint instead. Redacts by NAME
    (password/token/csrf/... keywords) OR by SHAPE (looks like a random
    token even under an innocuous name)."""
    if value is None or value == "":
        return {"present": bool(value == ""), "redacted": False, "value": value}
    name_l = (name or "").lower()
    looks_sensitive_name = any(w in name_l for w in SENSITIVE_KEYWORDS)
    looks_dynamic = (
        isinstance(value, str)
        and len(value) >= 20
        and bool(re.fullmatch(r"[A-Za-z0-9+/=_.-]{20,}", value))
    )
    if looks_sensitive_name or looks_dynamic:
        reason = "sensitive-name" if looks_sensitive_name else "looks-like-dynamic-token"
        return {"present": True, "redacted": True, "reason": reason, **describe_format(value)}
    return {"present": True, "redacted": False, "value": str(value)[:200]}


# ============================================================
# HELPERS — URL / domain
# ============================================================

def normalize_url(url, keep_query_names=True):
    try:
        p = urlparse(url)
        if keep_query_names:
            query = "&".join(f"{k}=[VALUE]" for k, _ in parse_qsl(p.query, keep_blank_values=True))
        else:
            query = ""
        return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, p.params, query, ""))
    except Exception:
        return redact_string(url)


def short_url(url):
    try:
        p = urlparse(url)
        result = p.path or "/"
        if p.query:
            result += "?"
        return result
    except Exception:
        return url


def safe_filename(url):
    p = urlparse(url)
    path = re.sub(r"[^a-zA-Z0-9_-]+", "_", p.path.strip("/") or "home")
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{path[:80]}_{digest}"


def origin(url):
    p = urlparse(url)
    return p.scheme.lower(), p.netloc.lower()


def registrable_domain(netloc):
    host = netloc.split(":")[0].lower().strip(".")
    if tldextract:
        ext = tldextract.extract(host)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        return host
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def same_origin(url_a, url_b):
    return origin(url_a) == origin(url_b)


def same_scope(url, scope_domain):
    return registrable_domain(origin(url)[1]) == scope_domain


def looks_static(url):
    try:
        path = urlparse(url).path.lower()
        return any(path.endswith(ext) for ext in STATIC_EXTENSIONS)
    except Exception:
        return False


def infrastructure_reason(url):
    try:
        p = urlparse(url)
        host = p.hostname or ""
        path = p.path.lower()
        if any(part in path for part in INFRA_PATH_PARTS):
            return "infrastructure-path"
        if any(part == host or host.endswith("." + part) for part in INFRA_HOST_PARTS):
            return "third-party-infrastructure"
    except Exception:
        pass
    return None


def looks_like_api_path(url):
    path = urlparse(url).path.lower()
    patterns = [
        "/api/", "/api", "/graphql", "/rest/", "/v1/", "/v2/", "/v3/",
        "/backend/", "/ajax/", "/rpc/",
    ]
    return any(p in path for p in patterns)


def is_business_request(request, in_scope):
    """Classify requests without relying only on /api/ naming.
    FIXED from v5: an xhr/fetch call now must ALSO be in_scope to count as
    business traffic. Previously any xhr/fetch, including third-party
    consent SDKs on a totally different domain, was unconditionally
    classified as business -- that's what put 51/59 Google consent-beacon
    calls into api_endpoints.json in the v5 test run."""
    if looks_static(request.url):
        return False
    if infrastructure_reason(request.url):
        return False
    rt = request.resource_type.lower()
    if rt in {"xhr", "fetch"}:
        return in_scope
    return looks_like_api_path(request.url) and in_scope


# ============================================================
# HELPERS — schema inference (request/response bodies)
# ============================================================

def infer_type(value):
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, (int, float)): return "number"
    if isinstance(value, str): return "string"
    if isinstance(value, list): return "array"
    if isinstance(value, dict): return "object"
    return "unknown"


def merge_schema(existing, value, depth=0, max_depth=4):
    typ = infer_type(value)
    if existing is None:
        existing = {"types": set(), "count": 0}
    existing["types"].add(typ)
    existing["count"] += 1
    if typ == "object" and depth < max_depth:
        fields = existing.setdefault("fields", {})
        for key, val in value.items():
            fields[key] = merge_schema(fields.get(key), val, depth + 1, max_depth)
    elif typ == "array" and depth < max_depth:
        items = existing.get("items")
        for item in value[:5]:
            items = merge_schema(items, item, depth + 1, max_depth)
        existing["items"] = items
    return existing


def serialize_schema(schema):
    if schema is None:
        return None
    out = {"types": sorted(schema["types"]), "observed": schema["count"]}
    if "fields" in schema:
        out["fields"] = {k: serialize_schema(v) for k, v in schema["fields"].items()}
    if "items" in schema:
        out["items"] = serialize_schema(schema["items"])
    return out


def deserialize_schema(data):
    """Inverse of serialize_schema. Used to load a previous run's schema
    back into the working (set-based) format so a new run can merge into it
    instead of starting from scratch."""
    if data is None:
        return None
    schema = {"types": set(data.get("types", [])), "count": data.get("observed", 0)}
    if "fields" in data:
        schema["fields"] = {k: deserialize_schema(v) for k, v in data["fields"].items()}
    if "items" in data:
        schema["items"] = deserialize_schema(data["items"])
    return schema


def post_data_json(request):
    try:
        value = request.post_data_json
        return value() if callable(value) else value
    except Exception:
        return None


def parse_multipart_names(body):
    if not body:
        return []
    return sorted(set(re.findall(r'name="([^"]+)"', body)))


def body_schema(request, headers):
    method = request.method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    try:
        content_type = headers.get("content-type", "").lower()
        if "application/json" in content_type:
            data = post_data_json(request)
            return serialize_schema(merge_schema(None, data)) if data is not None else None
        if "multipart/form-data" in content_type:
            return {"multipart_fields": parse_multipart_names(request.post_data)}
        if "application/x-www-form-urlencoded" in content_type:
            pairs = parse_qsl(request.post_data or "", keep_blank_values=True)
            return {"form_fields": sorted({k for k, _ in pairs})}
        return {"content_type": content_type or "unknown"}
    except Exception as exc:
        return {"error": f"body parse failed: {exc}"}


# ============================================================
# HELPERS — value-dependency tracking
# ============================================================

def collect_leaf_values(value, path="", depth=0, max_depth=6):
    """Walks a JSON structure and yields (path, string_value) for leaf
    values, skipping sensitive-looking keys and values outside a sane
    length range. Used to fingerprint values without storing full bodies
    twice."""
    results = []
    if depth > max_depth:
        return results
    if isinstance(value, dict):
        for k, v in value.items():
            if any(w in str(k).lower() for w in SENSITIVE_KEYWORDS):
                continue
            results.extend(collect_leaf_values(v, f"{path}.{k}" if path else str(k), depth + 1, max_depth))
    elif isinstance(value, list):
        for i, v in enumerate(value[:20]):
            results.extend(collect_leaf_values(v, f"{path}[{i}]", depth + 1, max_depth))
    elif isinstance(value, str):
        if MIN_VALUE_LEN_FOR_TRACKING <= len(value) <= MAX_VALUE_LEN_FOR_TRACKING:
            results.append((path, value))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        results.append((path, str(value)))
    return results


def value_hash(v):
    return hashlib.sha1(v.encode("utf-8", errors="ignore")).hexdigest()


# ============================================================
# JSON-safe dumping (handles sets, used by the error-safety net)
# ============================================================

def json_safe(obj):
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_safe(v) for v in obj]
    return obj


# ============================================================
# INVESTIGATOR
# ============================================================

class Investigator:
    def __init__(self, start_url):
        self.start_url = start_url
        self.scope_domain = registrable_domain(origin(start_url)[1])

        self.pages = []
        self.forms = []
        self.navigation = []
        self.clicks = []
        self.form_submissions = []
        self.network = []
        self.api_requests = []
        self.cross_origin_api_requests = []
        self.infrastructure_requests = []

        # SINGLE source of truth for every same-origin endpoint, whether it
        # was discovered via XHR/fetch or a classic HTML form POST. v5 kept
        # two separate dicts (self.endpoints / self.form_endpoints) that
        # could each be written independently -- that's what caused the
        # overwrite bugs. form_endpoints is now just a filtered view.
        self.endpoints = {}
        self.cross_origin_endpoints = {}

        self.recent_clicks = deque(maxlen=20)
        self.recent_form_submits = deque(maxlen=10)
        self.current_page = None
        self.page_number = 0
        self.request_number = 0

        # value-dependency tracking
        self.value_origins = {}   # hash -> {"endpoint","method","field_path","page"}
        self.value_links = []     # list of {"origin":..., "used_in":...}

    # --------------------------------------------------------
    def classify(self, request):
        in_scope = same_scope(request.url, self.scope_domain)
        infra = infrastructure_reason(request.url)
        business = is_business_request(request, in_scope)
        return in_scope, infra, business

    def new_entry(self, method, url, path):
        return {
            "method": method,
            "endpoint": url,
            "path": path,
            "resource_types": set(),
            "kinds": set(),
            "content_types": set(),
            "pages_seen_on": set(),
            "triggers": [],
            "request_schema": None,
            "request_schema_source": None,   # "network" or "dom-fallback"
            "response_schemas_by_status": {},
        }

    def get_or_create_entry(self, method, url, path):
        key = (method, url)
        if key not in self.endpoints:
            self.endpoints[key] = self.new_entry(method, url, path)
        return self.endpoints[key]

    # ========================================================
    # DOM extraction
    # ========================================================

    async def extract_forms(self, page):
        try:
            forms = await page.locator("form").evaluate_all(
                """
                (forms, maxOptions) => forms.map((form, formIndex) => ({
                    index: formIndex,
                    action: form.action || null,
                    method: (form.method || "GET").toUpperCase(),
                    id: form.id || null,
                    name: form.name || null,
                    enctype: form.enctype || null,
                    fields: Array.from(
                        form.querySelectorAll("input, textarea, select, button")
                    ).map((el, index) => {
                        const tag = el.tagName.toLowerCase();
                        const type = (el.type || "").toLowerCase();
                        const base = {
                            index, tag, type,
                            name: el.name || null,
                            id: el.id || null,
                            placeholder: el.placeholder || null,
                            aria_label: el.getAttribute("aria-label"),
                            autocomplete: el.autocomplete || null,
                            required: el.required ?? null,
                            disabled: el.disabled ?? null,
                            maxlength: (el.maxLength && el.maxLength > 0) ? el.maxLength : null,
                            minlength: (el.minLength && el.minLength > 0) ? el.minLength : null,
                            pattern: el.getAttribute("pattern"),
                            min: el.getAttribute("min"),
                            max: el.getAttribute("max"),
                            step: el.getAttribute("step"),
                            accept: el.getAttribute("accept"),
                            multiple: el.multiple ?? null,
                        };
                        if (tag === "select") {
                            base.options = Array.from(el.options)
                                .slice(0, maxOptions)
                                .map(o => ({
                                    value: o.value,
                                    text: (o.text || "").trim().slice(0, 150),
                                    selected: o.selected
                                }));
                            base.options_truncated = el.options.length > maxOptions;
                            base.options_total = el.options.length;
                        }
                        if (type === "radio" || type === "checkbox") {
                            base.value_attr = el.value;
                            base.checked = el.checked;
                        }
                        if (type === "hidden") {
                            base.raw_value = el.value;
                        }
                        return base;
                    })
                }))
                """,
                MAX_OPTIONS_PER_SELECT,
            )
            forms = self._post_process_forms(forms)
            return redact_object(forms)
        except Exception as exc:
            print(f"[!] Form extraction failed: {exc}")
            return []

    def _post_process_forms(self, forms):
        """Applies the hidden-value classifier (name + shape based
        redaction) after extraction, since that logic lives in Python."""
        for form in forms:
            for field in form.get("fields", []):
                if field.get("type") == "hidden" and "raw_value" in field:
                    classification = classify_hidden_value(field.get("name"), field.pop("raw_value"))
                    field["hidden_value"] = classification
        return forms

    async def extract_interactive(self, page):
        try:
            elements = await page.locator(
                "input, textarea, select, button, a"
            ).evaluate_all(
                """
                elements => elements.map((el, index) => ({
                    index,
                    tag: el.tagName.toLowerCase(),
                    type: el.type || null,
                    id: el.id || null,
                    name: el.name || null,
                    role: el.getAttribute("role"),
                    aria_label: el.getAttribute("aria-label"),
                    placeholder: el.getAttribute("placeholder"),
                    title: el.getAttribute("title"),
                    text: (el.innerText || el.value || "").trim().slice(0, 150),
                    href: el.href || null,
                    required: el.required ?? null,
                    disabled: el.disabled ?? null
                }))
                """
            )
            return redact_object(elements)
        except Exception as exc:
            print(f"[!] Interactive extraction failed: {exc}")
            return []

    async def extract_frames(self, page):
        frames = []
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            frames.append({
                "url": normalize_url(frame.url),
                "same_origin": same_origin(frame.url, page.url) if frame.url else False,
            })
        return frames

    async def capture_page(self, page, reason="navigation"):
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(600)

        self.page_number += 1
        number = self.page_number
        url = page.url
        title = await page.title()
        filename = safe_filename(url)
        page_dir = OUTPUT_DIR / "pages"
        screenshot_dir = OUTPUT_DIR / "screenshots"
        page_dir.mkdir(parents=True, exist_ok=True)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        try:
            html = await page.content()
            (page_dir / f"{number:03d}_{filename}.html").write_text(html, encoding="utf-8")
        except Exception as exc:
            print(f"[!] DOM snapshot failed: {exc}")

        try:
            await page.screenshot(path=str(screenshot_dir / f"{number:03d}_{filename}.png"), full_page=True)
        except Exception as exc:
            print(f"[!] Screenshot failed: {exc}")

        forms = await self.extract_forms(page)
        interactive = await self.extract_interactive(page)
        frames = await self.extract_frames(page)
        self.forms.extend(forms)

        page_data = {
            "page": number,
            "timestamp": now(),
            "url": normalize_url(url),
            "title": title,
            "reason": reason,
            "forms": forms,
            "interactive_elements": interactive,
            "frames": frames,
        }
        self.pages.append(page_data)
        self.navigation.append({
            "timestamp": now(), "page": number, "url": normalize_url(url),
            "title": title, "reason": reason,
        })
        self.current_page = number
        print(f"\n[PAGE {number}] ({reason}) {short_url(url)}")
        print(f"  Forms: {len(forms)}  Interactive: {len(interactive)}  Frames: {len(frames)}")

    async def capture_dynamic_state(self, page, reason="dom-mutation"):
        await page.wait_for_timeout(MUTATION_DEBOUNCE_MS)
        try:
            forms = await self.extract_forms(page)
            interactive = await self.extract_interactive(page)
            self.forms.extend(forms)
            event = {
                "timestamp": now(),
                "page": self.current_page,
                "url": normalize_url(page.url),
                "reason": reason,
                "forms_detected": len(forms),
                "interactive_detected": len(interactive),
            }
            self.navigation.append(event)
            print(f"[DOM CHANGE] page={self.current_page} forms={len(forms)} interactive={len(interactive)}")
        except Exception:
            pass

    # ========================================================
    # REQUEST / RESPONSE
    # ========================================================

    async def request(self, request, network_file):
        self.request_number += 1
        in_scope, infra, business = self.classify(request)
        headers = {}
        try:
            headers = await request.all_headers()
        except Exception:
            pass

        record = {
            "id": self.request_number,
            "timestamp": now(),
            "method": request.method.upper(),
            "url": normalize_url(request.url),
            "path": short_url(request.url),
            "resource_type": request.resource_type,
            "in_scope": in_scope,
            "classification": "infrastructure" if infra else ("business_api" if business else ("same_scope_non_api" if in_scope else "cross_origin")),
            "infrastructure_reason": infra,
            "page": self.current_page,
        }
        try:
            record["headers"] = redact_headers(headers)
        except Exception:
            record["headers"] = {}

        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            record["body_present"] = request.post_data is not None
            record["body_schema"] = body_schema(request, headers)

        trigger = self.find_trigger()
        if trigger:
            record["triggered_by"] = trigger

        network_file.write(json.dumps(redact_object(record), ensure_ascii=False) + "\n")
        network_file.flush()
        self.network.append(record)

        if infra:
            self.infrastructure_requests.append(record)
            return

        # Value-dependency tracking: does this request reuse a value we saw
        # in a prior response?
        if in_scope and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            content_type = headers.get("content-type", "").lower()
            body_data = None
            if "application/json" in content_type:
                body_data = post_data_json(request)
            elif "application/x-www-form-urlencoded" in content_type:
                body_data = dict(parse_qsl(request.post_data or "", keep_blank_values=True))
            if body_data is not None:
                self._check_value_links(body_data, record)

        # Classic HTML form POST/PUT/etc. is a business operation even when
        # it's not XHR/fetch.
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and in_scope and not looks_static(request.url):
            self.add_endpoint(record, request, headers, kind="form_or_navigation")

        if business:
            self.add_endpoint(record, request, headers, kind="xhr_fetch_or_api_path")
            self.api_requests.append(record)
            print(f"[API] {request.method.upper():7} {short_url(request.url)}")
        elif not in_scope and request.resource_type.lower() in {"xhr", "fetch"}:
            self.add_cross_origin(record, request)

    def _check_value_links(self, body_data, record):
        for path, val in collect_leaf_values(body_data):
            h = value_hash(val)
            origin_info = self.value_origins.get(h)
            if origin_info and len(self.value_links) < MAX_VALUE_LINKS:
                self.value_links.append({
                    "origin": origin_info,
                    "used_in": {
                        "endpoint": f"{record['method']} {record['path']}",
                        "field_path": path,
                        "page": self.current_page,
                    },
                })

    def find_trigger(self):
        now_dt = datetime.now()
        candidates = []
        if self.recent_clicks:
            c = self.recent_clicks[-1]
            if (now_dt - c["_ts"]).total_seconds() <= CLICK_CORRELATION_WINDOW_SECONDS:
                candidates.append((c["_ts"], {k: v for k, v in c.items() if k != "_ts"}, "click"))
        if self.recent_form_submits:
            f = self.recent_form_submits[-1]
            if (now_dt - f["_ts"]).total_seconds() <= CLICK_CORRELATION_WINDOW_SECONDS:
                candidates.append((f["_ts"], {k: v for k, v in f.items() if k != "_ts"}, "form_submit"))
        if not candidates:
            return None
        _, data, kind = max(candidates, key=lambda x: x[0])
        data["trigger_type"] = kind
        return data

    def add_endpoint(self, record, request, headers, kind):
        entry = self.get_or_create_entry(record["method"], record["url"], record["path"])
        entry["resource_types"].add(record["resource_type"])
        entry["kinds"].add(kind)
        entry["pages_seen_on"].add(self.current_page)
        content_type = headers.get("content-type", "").lower()
        if content_type:
            entry["content_types"].add(content_type.split(";")[0].strip())

        if record.get("triggered_by"):
            if len(entry["triggers"]) < 30:
                entry["triggers"].append(record["triggered_by"])

        bs = record.get("body_schema")
        if bs and "application/json" in content_type:
            data = post_data_json(request)
            if data is not None:
                entry["request_schema"] = merge_schema(entry["request_schema"], data)
                entry["request_schema_source"] = "network"
        elif bs and ("form_fields" in bs or "multipart_fields" in bs):
            field_names = bs.get("form_fields", []) + bs.get("multipart_fields", [])
            if field_names:
                fake_body = {name: "" for name in field_names}
                entry["request_schema"] = merge_schema(entry["request_schema"], fake_body)
                entry["request_schema_source"] = "network"
            # if field_names is empty (e.g. a real file upload where
            # Playwright couldn't capture the wire body), leave
            # request_schema alone here -- the DOM fallback pass in
            # generate_reports() will try to fill it from forms.json.

        return entry

    def add_cross_origin(self, record, request):
        key = (record["method"], record["url"])
        entry = self.cross_origin_endpoints.setdefault(key, {
            "method": record["method"], "endpoint": record["url"], "path": record["path"],
            "resource_type": record["resource_type"], "pages_seen_on": set()
        })
        entry["pages_seen_on"].add(self.current_page)
        self.cross_origin_api_requests.append(record)

    async def response(self, response, network_file):
        request = response.request
        in_scope, infra, business = self.classify(request)
        if infra:
            return
        if not business and not (in_scope and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}):
            return

        headers = {}
        try:
            headers = await response.all_headers()
        except Exception:
            pass
        record = {
            "timestamp": now(),
            "type": "api_response",
            "method": request.method.upper(),
            "url": normalize_url(response.url),
            "path": short_url(response.url),
            "status": response.status,
            "status_text": response.status_text,
            "in_scope": in_scope,
            "page": self.current_page,
        }
        record["headers"] = redact_headers(headers)

        content_type = headers.get("content-type", "").lower()
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = 0

        if "application/json" in content_type and (not length or length <= MAX_BODY_BYTES):
            try:
                data = await response.json()
                schema = merge_schema(None, data)
                record["response_schema"] = serialize_schema(schema)

                key = (request.method.upper(), normalize_url(request.url))
                if key in self.endpoints:
                    current = self.endpoints[key]["response_schemas_by_status"].get(str(response.status))
                    self.endpoints[key]["response_schemas_by_status"][str(response.status)] = merge_schema(current, data)

                # Record leaf values as candidate "origins" for later
                # value-dependency detection, only for in-scope responses.
                if in_scope:
                    endpoint_label = f"{request.method.upper()} {short_url(response.url)}"
                    for path, val in collect_leaf_values(data):
                        h = value_hash(val)
                        self.value_origins.setdefault(h, {
                            "endpoint": endpoint_label,
                            "field_path": path,
                            "page": self.current_page,
                        })
            except Exception:
                pass

        network_file.write(json.dumps(redact_object(record), ensure_ascii=False) + "\n")
        network_file.flush()

    # ========================================================
    # CLICK / FORM SUBMIT
    # ========================================================

    async def record_click(self, info):
        info = redact_object(info or {})
        if str(info.get("type", "")).lower() == "password":
            info["text"] = "[PASSWORD_FIELD]"
        event = {"timestamp": now(), "page": self.current_page, **info}
        self.clicks.append(event)
        self.recent_clicks.append({**info, "page": self.current_page, "_ts": datetime.now()})
        label = info.get("text") or info.get("aria_label") or info.get("id") or info.get("name") or info.get("tag")
        print(f"[CLICK] {label}")

    async def record_form_submit(self, info):
        info = redact_object(info or {})
        event = {"timestamp": now(), "page": self.current_page, **info}
        self.form_submissions.append(event)
        self.recent_form_submits.append({**info, "page": self.current_page, "_ts": datetime.now()})
        action = info.get("action") or ""
        method = info.get("method", "GET").upper()

        # Register immediately, in the SAME store add_endpoint() writes to.
        # If the matching network request arrives later, add_endpoint()
        # updates this exact entry (schema, triggers, kind) instead of a
        # separate object that would silently shadow this one.
        if self.current_page is not None and method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            url = normalize_url(action)
            entry = self.get_or_create_entry(method, url, short_url(action))
            entry["kinds"].add("html_form_submission")
            entry["pages_seen_on"].add(self.current_page)

        print(f"[FORM SUBMIT] {method} {action}")

    # ========================================================
    # DOM FALLBACK for multipart/file fields whose wire body was empty
    # ========================================================

    def apply_dom_fallback_for_multipart(self):
        for (method, url), entry in self.endpoints.items():
            if "multipart/form-data" not in entry.get("content_types", set()):
                continue
            has_fields = bool(entry.get("request_schema") and entry["request_schema"].get("fields"))
            if has_fields:
                continue
            # Find a matching form in the DOM captures (same action + method)
            for form in self.forms:
                form_action = normalize_url(form.get("action") or "")
                form_method = (form.get("method") or "GET").upper()
                if form_action == url and form_method == method:
                    field_names = [f.get("name") for f in form.get("fields", []) if f.get("name")]
                    if field_names:
                        fake_body = {name: "" for name in field_names}
                        entry["request_schema"] = merge_schema(entry["request_schema"], fake_body)
                        entry["request_schema_source"] = "dom-fallback"
                    break

    # ========================================================
    # CUMULATIVE LOAD / SAVE
    # ========================================================

    def load_cumulative(self, cumulative_dir):
        api_path = cumulative_dir / "api_endpoints.json"
        cross_path = cumulative_dir / "cross_origin_endpoints.json"
        if api_path.exists():
            try:
                data = json.loads(api_path.read_text(encoding="utf-8"))
                for ep in data.get("endpoints", []):
                    key = (ep["method"], ep["endpoint"])
                    entry = self.new_entry(ep["method"], ep["endpoint"], ep["path"])
                    entry["resource_types"] = set(ep.get("resource_types", []))
                    entry["kinds"] = set(ep.get("kinds", []))
                    entry["content_types"] = set(ep.get("content_types", []))
                    entry["pages_seen_on"] = set()  # page numbers aren't meaningful across runs
                    entry["triggers"] = ep.get("triggers", [])[:30]
                    entry["request_schema"] = deserialize_schema(ep.get("request_schema"))
                    entry["request_schema_source"] = ep.get("request_schema_source")
                    entry["response_schemas_by_status"] = {
                        status: deserialize_schema(schema)
                        for status, schema in ep.get("response_schemas_by_status", {}).items()
                    }
                    self.endpoints[key] = entry
                print(f"[*] Loaded {len(data.get('endpoints', []))} endpoints from cumulative store.")
            except Exception as exc:
                print(f"[!] Could not load cumulative data: {exc}")

    # ========================================================
    # REPORTS
    # ========================================================

    def endpoint_report(self, endpoint_map):
        result = []
        for entry in endpoint_map.values():
            result.append({
                "method": entry["method"],
                "endpoint": entry["endpoint"],
                "path": entry["path"],
                "resource_types": sorted(entry.get("resource_types", [])),
                "kinds": sorted(entry.get("kinds", [])),
                "content_types": sorted(entry.get("content_types", [])),
                "pages_seen_on": sorted(x for x in entry.get("pages_seen_on", set()) if x is not None),
                "triggers": entry.get("triggers", []),
                "request_schema": serialize_schema(entry.get("request_schema")),
                "request_schema_source": entry.get("request_schema_source"),
                "response_schemas_by_status": {
                    status: serialize_schema(schema)
                    for status, schema in entry.get("response_schemas_by_status", {}).items()
                },
            })
        return sorted(result, key=lambda x: (x["path"], x["method"]))

    def form_write_endpoints_report(self):
        """Filtered VIEW over self.endpoints -- not a separate store."""
        subset = {
            k: v for k, v in self.endpoints.items()
            if v["kinds"] & {"html_form_submission", "form_or_navigation"}
        }
        return self.endpoint_report(subset)

    def business_workflow(self):
        events = []
        for e in self.navigation:
            if e.get("reason") in {"initial", "navigation", "popup"}:
                events.append({"timestamp": e["timestamp"], "type": "page", "page": e.get("page"), "url": e.get("url"), "reason": e.get("reason")})
        for e in self.clicks:
            events.append({"timestamp": e["timestamp"], "type": "click", "page": e.get("page"), "label": e.get("text") or e.get("aria_label") or e.get("id") or e.get("name"), "tag": e.get("tag")})
        for e in self.form_submissions:
            events.append({"timestamp": e["timestamp"], "type": "form_submit", "page": e.get("page"), "method": e.get("method"), "action": normalize_url(e.get("action", ""))})
        for e in self.api_requests:
            events.append({"timestamp": e["timestamp"], "type": "api", "page": e.get("page"), "method": e.get("method"), "endpoint": e.get("url"), "triggered_by": e.get("triggered_by"), "body_schema": e.get("body_schema")})
        return sorted(events, key=lambda x: x["timestamp"])

    def generate_reports(self):
        """Wrapped in a safety net: if structured report generation fails
        partway through, dump the raw internal state instead of losing the
        whole capture session (this is what bit us on the v5 socket-crash
        run)."""
        try:
            self._generate_reports_inner()
        except Exception as exc:
            print(f"[!] generate_reports() failed: {exc}")
            print("[!] Writing raw fallback dump instead of a formatted report...")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            fallback = {
                "error": str(exc),
                "endpoints": json_safe(self.endpoints),
                "cross_origin_endpoints": json_safe(self.cross_origin_endpoints),
                "pages": self.pages,
                "forms": self.forms,
                "navigation": self.navigation,
                "clicks": self.clicks,
                "form_submissions": self.form_submissions,
                "value_links": self.value_links,
            }
            (OUTPUT_DIR / "RAW_DUMP_ON_ERROR.json").write_text(
                json.dumps(fallback, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            print(f"[*] Raw dump saved to {OUTPUT_DIR / 'RAW_DUMP_ON_ERROR.json'}")

    def _generate_reports_inner(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # DOM fallback pass for multipart/file endpoints before reporting.
        self.apply_dom_fallback_for_multipart()

        (OUTPUT_DIR / "pages.json").write_text(json.dumps(self.pages, indent=2, ensure_ascii=False), encoding="utf-8")
        (OUTPUT_DIR / "forms.json").write_text(json.dumps(self.forms, indent=2, ensure_ascii=False), encoding="utf-8")

        api = {"application": self.start_url, "scope_domain": self.scope_domain, "endpoints": self.endpoint_report(self.endpoints)}
        (OUTPUT_DIR / "api_endpoints.json").write_text(json.dumps(api, indent=2, ensure_ascii=False), encoding="utf-8")

        cross = {"endpoints": self.endpoint_report(self.cross_origin_endpoints)}
        (OUTPUT_DIR / "cross_origin_endpoints.json").write_text(json.dumps(cross, indent=2, ensure_ascii=False), encoding="utf-8")

        form_api = {
            "note": "Filtered view of api_endpoints.json: entries seen as a classic HTML form submission.",
            "endpoints": self.form_write_endpoints_report(),
        }
        (OUTPUT_DIR / "form_endpoints.json").write_text(json.dumps(form_api, indent=2, ensure_ascii=False), encoding="utf-8")

        (OUTPUT_DIR / "field_dependencies.json").write_text(
            json.dumps({
                "note": "Response fields whose VALUE (hashed, never stored raw) reappeared in a later request. Indicates a required chained value, e.g. a search result id used in a subsequent save call.",
                "links": self.value_links,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        workflow = {
            "application": self.start_url,
            "generated_at": now(),
            "navigation": self.navigation,
            "clicks": self.clicks,
            "form_submissions": self.form_submissions,
            "api_requests": self.api_requests,
            "business_workflow": self.business_workflow(),
        }
        (OUTPUT_DIR / "workflow.json").write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")

        summary = {
            "application": self.start_url,
            "scope_domain": self.scope_domain,
            "pages": len(self.pages),
            "forms": len(self.forms),
            "clicks": len(self.clicks),
            "form_submissions": len(self.form_submissions),
            "network_requests": len(self.network),
            "business_api_requests": len(self.api_requests),
            "cross_origin_api_requests": len(self.cross_origin_api_requests),
            "infrastructure_requests": len(self.infrastructure_requests),
            "unique_business_endpoints": len(self.endpoints),
            "unique_form_write_endpoints": len(self.form_write_endpoints_report()),
            "field_dependency_links": len(self.value_links),
        }
        (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        self.write_report(summary, api, cross, form_api)

        # Persist to cumulative store for future runs.
        CUMULATIVE_DIR.mkdir(parents=True, exist_ok=True)
        (CUMULATIVE_DIR / "api_endpoints.json").write_text(json.dumps(api, indent=2, ensure_ascii=False), encoding="utf-8")
        (CUMULATIVE_DIR / "cross_origin_endpoints.json").write_text(json.dumps(cross, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[*] Cumulative store updated at {CUMULATIVE_DIR.resolve()}")

    def write_report(self, summary, api, cross, form_api):
        lines = ["# Website Investigation V6", "", f"Application: `{self.start_url}`", f"Scope domain: `{self.scope_domain}`", "", "## Summary", ""]
        lines += [f"- {k}: {v}" for k, v in summary.items()]

        lines += ["", "## Business endpoints", ""]
        for ep in api["endpoints"]:
            lines.append(f"### `{ep['method']}` `{ep['path']}`")
            lines.append(f"- kinds: {', '.join(ep['kinds'])}")
            lines.append(f"- pages: {ep['pages_seen_on']}")
            if ep["triggers"]:
                lines.append(f"- triggers: {len(ep['triggers'])}")
            if ep["request_schema"]:
                source = ep.get("request_schema_source") or "network"
                lines.append(f"- request schema present (source: {source}):")
                for name, sub in list(ep["request_schema"].get("fields", {}).items())[:30]:
                    lines.append(f"  - `{name}`: {sub['types']}")
            if ep["response_schemas_by_status"]:
                lines.append(f"- response statuses: {', '.join(ep['response_schemas_by_status'])}")
            lines.append("")

        lines += ["## Form/write endpoints (filtered view)", ""]
        for ep in form_api["endpoints"]:
            lines.append(f"- `{ep['method']}` `{ep['path']}` — {', '.join(ep['kinds'])}")

        lines += ["", "## Field dependencies (response value reused in a later request)", ""]
        if not self.value_links:
            lines.append("None detected.")
        for link in self.value_links[:100]:
            lines.append(f"- `{link['origin']['endpoint']}` field `{link['origin']['field_path']}` → `{link['used_in']['endpoint']}` field `{link['used_in']['field_path']}`")

        lines += ["", "## Forms with select options / hidden fields / constraints", ""]
        for form in self.forms:
            interesting_fields = [
                f for f in form.get("fields", [])
                if f.get("options") or f.get("type") in {"hidden", "radio", "checkbox"} or f.get("pattern") or f.get("maxlength")
            ]
            if not interesting_fields:
                continue
            lines.append(f"### Form `{form.get('id') or form.get('name') or form.get('action')}`")
            for f in interesting_fields:
                label = f.get("name") or f.get("id") or f.get("type")
                extra = []
                if f.get("options"):
                    opt_preview = ", ".join(o["value"] for o in f["options"][:10])
                    more = " (+more)" if f.get("options_truncated") else ""
                    extra.append(f"options: [{opt_preview}]{more}")
                if f.get("type") == "hidden" and f.get("hidden_value"):
                    hv = f["hidden_value"]
                    if hv.get("redacted"):
                        extra.append(f"hidden value redacted ({hv.get('reason')}, {hv.get('format')}, len={hv.get('length')})")
                    elif hv.get("present"):
                        extra.append(f"hidden value: `{hv.get('value')}`")
                if f.get("pattern"):
                    extra.append(f"pattern: `{f['pattern']}`")
                if f.get("maxlength"):
                    extra.append(f"maxlength: {f['maxlength']}")
                lines.append(f"- `{label}` ({f.get('type')}) — {'; '.join(extra)}")
            lines.append("")

        lines += ["", "## Cross-origin API", ""]
        for ep in cross["endpoints"]:
            lines.append(f"- `{ep['method']}` `{ep['path']}`")
        if not cross["endpoints"]:
            lines.append("None detected.")

        lines += ["", "## Recent workflow", ""]
        for e in self.business_workflow()[-100:]:
            if e["type"] == "click":
                lines.append(f"- CLICK page {e['page']}: `{e['label']}`")
            elif e["type"] == "api":
                trigger = e.get("triggered_by")
                lines.append(f"- API page {e['page']}: `{e['method']} {e['endpoint']}`" + (f" ← {trigger.get('text') or trigger.get('aria_label') or trigger.get('id')}" if trigger else ""))
            elif e["type"] == "form_submit":
                lines.append(f"- FORM page {e['page']}: `{e['method']} {e['action']}`")
            elif e["type"] == "page":
                lines.append(f"- PAGE {e['url']}")

        (OUTPUT_DIR / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# BROWSER INSTRUMENTATION
# ============================================================

CLICK_SCRIPT = r"""
(() => {
  if (window.__investigator_v6_installed) return;
  window.__investigator_v6_installed = true;
  document.addEventListener('click', event => {
    const el = event.target.closest('button, a, input, select, textarea, [role="button"]');
    if (!el) return;
    const type = (el.getAttribute('type') || '').toLowerCase();
    window.__investigator_click({
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      name: el.getAttribute('name') || null,
      type,
      text: type === 'password' ? '[PASSWORD_FIELD]' : (el.innerText || el.value || '').trim().slice(0,150),
      aria_label: el.getAttribute('aria-label'),
      href: el.href || null
    });
  }, true);
})();
"""

FORM_SCRIPT = r"""
(() => {
  if (window.__investigator_v6_forms) return;
  window.__investigator_v6_forms = true;
  document.addEventListener('submit', event => {
    const form = event.target;
    window.__investigator_form({
      method: (form.method || 'GET').toUpperCase(),
      action: form.action || location.href,
      id: form.id || null,
      name: form.name || null
    });
  }, true);
})();
"""

MUTATION_SCRIPT = r"""
(() => {
  if (window.__investigator_v6_mutation) return;
  window.__investigator_v6_mutation = true;
  let timer = null;
  const observer = new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      window.__investigator_dom_mutation({ url: location.href });
    }, 700);
  });
  const start = () => {
    if (document.documentElement) observer.observe(document.documentElement, {childList:true, subtree:true, attributes:true});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
"""


async def instrument_page(page, investigator, network_file):
    async def on_request(request):
        try:
            await investigator.request(request, network_file)
        except Exception as exc:
            print(f"[!] Request handler: {exc}")

    async def on_response(response):
        try:
            await investigator.response(response, network_file)
        except Exception as exc:
            print(f"[!] Response handler: {exc}")

    async def on_click(info):
        await investigator.record_click(info)

    async def on_form(info):
        await investigator.record_form_submit(info)

    async def on_mutation(info):
        try:
            await investigator.capture_dynamic_state(page, "dom-mutation")
        except Exception:
            pass

    page.on("request", on_request)
    page.on("response", on_response)
    await page.expose_function("__investigator_click", on_click)
    await page.expose_function("__investigator_form", on_form)
    await page.expose_function("__investigator_dom_mutation", on_mutation)
    await page.add_init_script(CLICK_SCRIPT)
    await page.add_init_script(FORM_SCRIPT)
    await page.add_init_script(MUTATION_SCRIPT)


# ============================================================
# MAIN
# ============================================================

async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    network_dir = OUTPUT_DIR / "network"
    network_dir.mkdir(parents=True, exist_ok=True)
    network_file = (network_dir / "requests.jsonl").open("w", encoding="utf-8")

    print("=" * 70)
    print("                 WEBSITE INVESTIGATOR V6")
    print("=" * 70)
    print("New in V6:")
    print("  1. Select options, radio/checkbox values, hidden field values")
    print("     (redacted by name AND by shape/entropy)")
    print("  2. Field constraints: pattern, min/max length, min/max, step, accept")
    print("  3. Unified endpoint storage (fixes the v5 overwrite-race bugs)")
    print("  4. Value-dependency tracking: response field -> later request field")
    print("     (hash-based, never stores the actual value twice)")
    print("  5. DOM fallback for multipart/file fields when the wire body is empty")
    print("  6. Cumulative store: merges schemas across multiple runs")
    print("  7. Cross-origin scoping bug fixed (was: any xhr/fetch counted as")
    print("     business traffic regardless of domain)")
    print("  8. Report generation wrapped in a safety net (raw dump on failure)")
    print("=" * 70)
    print()

    start_url = input("Enter starting URL: ").strip()
    if not start_url.startswith(("http://", "https://")):
        print("[ERROR] Enter a complete URL, e.g. https://example.com/")
        network_file.close()
        return

    investigator = Investigator(start_url)

    if CUMULATIVE_DIR.exists() and (CUMULATIVE_DIR / "api_endpoints.json").exists():
        merge = input(
            f"Found previous cumulative data in {CUMULATIVE_DIR}/. "
            f"Merge it into this run? (Y/n): "
        ).strip().lower()
        if merge in ("", "y", "yes"):
            investigator.load_cumulative(CUMULATIVE_DIR)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            record_har_path=str(network_dir / "investigation.har"),
            record_har_content="omit",
        )

        page = await context.new_page()
        await instrument_page(page, investigator, network_file)

        async def on_new_page(new_page):
            try:
                await instrument_page(new_page, investigator, network_file)
                await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                await investigator.capture_page(new_page, reason="popup")
            except Exception as exc:
                print(f"[!] Popup instrumentation failed: {exc}")

        context.on("page", lambda p_: asyncio.create_task(on_new_page(p_)))

        print("[*] Opening website...")
        await page.goto(start_url, wait_until="domcontentloaded")
        await investigator.capture_page(page, reason="initial")

        last_url = page.url

        async def navigation_watcher():
            nonlocal last_url
            while True:
                await asyncio.sleep(0.4)
                try:
                    current = page.url
                    if current != last_url:
                        last_url = current
                        await investigator.capture_page(page, reason="navigation")
                except Exception:
                    pass

        watcher = asyncio.create_task(navigation_watcher())

        print()
        print("=" * 70)
        print("BROWSER READY — perform the workflow manually")
        print("=" * 70)
        print("Recommended test:")
        print("  1. Login")
        print("  2. Search")
        print("  3. Select an item/dossier")
        print("  4. Open the form")
        print("  5. Fill dummy/test data — try different dropdown choices if you")
        print("     re-run this later, to capture conditional fields")
        print("  6. Save/submit")
        print("  7. If a modal, iframe, popup or second tab appears, use it")
        print("  8. Return here and press ENTER")
        print()

        await asyncio.to_thread(input, "Press ENTER to finish...")
        watcher.cancel()
        await page.wait_for_timeout(1200)

        investigator.generate_reports()
        network_file.close()

        save_session = input("Save authenticated session state? Contains live cookies (y/N): ").strip().lower()
        if save_session == "y":
            auth_path = OUTPUT_DIR / "auth_state.json"
            await context.storage_state(path=str(auth_path))
            print(f"[*] Session saved: {auth_path}")

        await context.close()
        await browser.close()

    print("\n" + "=" * 70)
    print("V6 COMPLETE")
    print("=" * 70)
    print(f"Output: {OUTPUT_DIR.resolve()}")
    print(f"Cumulative store: {CUMULATIVE_DIR.resolve()}")
    print("\nImportant files:")
    print("  REPORT.md")
    print("  api_endpoints.json")
    print("  form_endpoints.json")
    print("  field_dependencies.json   <- NEW")
    print("  forms.json                <- now includes options/hidden/constraints")
    print("  workflow.json")
    print("  summary.json")
    print("  network/investigation.har")
    print("  network/requests.jsonl")


if __name__ == "__main__":
    asyncio.run(main())