You are analyzing the output of a browser-based reconnaissance tool that captured a real authenticated workflow on an internal insurance company web application. The goal is NOT to summarize the files — it's to produce a concrete implementation plan for a Python automation agent that will log in, search for a dossier, fill a form, and save it, calling the company's own HTTP endpoints directly wherever possible (falling back to browser automation only where the data below is insufficient).

## Files you have

- `summary.json` — run-level counts (pages, endpoints, requests)
- `api_endpoints.json` — every same-origin business endpoint hit during the workflow, each with: method, path, resource type(s), how it was triggered, `request_schema` (inferred field names/types — check `request_schema_source`: "network" means captured from a real request body, "dom-fallback" means inferred from the HTML form instead because the real request body wasn't capturable, e.g. file uploads), and `response_schemas_by_status` (inferred shape of JSON responses per HTTP status code)
- `form_endpoints.json` — filtered view of the above: only classic HTML form POSTs (as opposed to XHR/fetch calls)
- `field_dependencies.json` — pairs where a value from one response reappeared in a later request (e.g. a dossier ID from a search result reused in a save call). Values themselves are NEVER stored, only field-name-to-field-name links via hash matching, so treat any entry here as "these two fields are almost certainly the same piece of data flowing through the workflow," not as literal data.
- `forms.json` — DOM-level detail per page: every form field, including `<select>` options (value + label), radio/checkbox values, hidden field values (redacted if they looked like a credential/token/PII — check for a `hidden_value.redacted: true` flag with a `format`/`reason` before assuming a field is static vs. dynamically issued per session), and validation constraints (`pattern`, `maxlength`, `min`, `max`, `required`, etc.)
- `workflow.json` — the full sequence: navigation, clicks, form submissions, and API calls in chronological order, with each API call's `triggered_by` showing which click/submit caused it
- `REPORT.md` — human-readable digest of all of the above

## What I need from you

1. **Reconstruct the end-to-end flow** as an ordered list of steps (auth → search → select → fill → save), citing the specific endpoint(s) involved in each step. Cross-reference `workflow.json`'s chronological order with `api_endpoints.json`'s schemas.

2. **Authentication strategy**: identify whether login is a classic form POST (session/cookie-based) or a token-issuing API call (JWT/bearer). If there's a CSRF-style hidden field, tell me whether it's static (safe to hardcode) or dynamic (must be scraped fresh before each session) based on the `hidden_value` classification in `forms.json`. Recommend how the agent should acquire and store the session (cookies via `requests.Session`/httpx, or a bearer token to attach as a header).

3. **The save/submit endpoint's exact required payload**: give me the full field list with types, sourced from whichever entry has `request_schema_source: "network"` (trust this) vs `"dom-fallback"` (flag this explicitly — it means we only know the field NAMES exist, not confirmed types or whether the server actually accepts them via direct API call rather than full form navigation).

4. **Chained values**: walk `field_dependencies.json` and tell me, in plain language, which value from which earlier response must be captured and threaded into which later request. This is the part a stateless direct-API client will get wrong if missed.

5. **Every dropdown/select/radio the form depends on**, with their exact valid `value` (not label) from `forms.json`, since the server will reject anything outside that set.

6. **Gaps and unknowns** — be explicit and conservative here, don't guess:
   - Any endpoint with `request_schema: null` — flag it as unconfirmed and explain what a follow-up capture run would need to trigger to fill it in.
   - Any field whose `request_schema_source` is `"dom-fallback"` — flag that this needs a live-browser confirmation before trusting a direct API call for it.
   - Any select/dropdown whose options look incomplete or empty in `forms.json` (e.g. populated dynamically after some other action).
   - Anything you can't determine from these files alone (e.g. conditional fields that only appear based on another field's value, validation rules beyond `pattern`/`maxlength`, rate limits, pagination on search results).

7. **Recommended agent architecture**: for each step in the flow, tell me whether it should be a direct HTTP call (fast, cheap, reliable — use when we have a confirmed `request_schema` from `"network"` source) or should stay browser-driven via Playwright/browser-use with LLM reasoning (use when the schema is missing, `dom-fallback`-sourced, or the field is a non-native/JS-rendered control not captured here at all).

## Constraints

- Do not invent field values, endpoint paths, or schema details that aren't present in the files — if something is ambiguous, say so and tell me what additional capture run would resolve it, rather than filling the gap with a plausible guess.
- Treat every redacted value (`[REDACTED]`, `hidden_value.redacted: true`) as genuinely unknown — do not attempt to infer or reconstruct what it might be.
- Output a structured markdown report with the sections above, plus a final "Ready to build" checklist of what we have confirmed vs. what still needs a targeted follow-up capture before the agent can be built against it.
