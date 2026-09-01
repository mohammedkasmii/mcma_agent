# api

The single place HTTP happens and the single place errors are shaped. UI
components never call `fetch` and never see a snake_case response object.

- `client.ts` — same-origin requests with `credentials: "include"`, central
  JSON parsing, and every failure normalized into an `ApiError` carried by
  `ApiRequestError`. State-changing methods attach the `X-CSRF-Token` header;
  no application code sends one yet.
- `csrf.ts` — reads the non-HttpOnly `mcma_csrf` cookie. The session cookie is
  HttpOnly and is never read here.
- `errors.ts` — pure normalizer. Only the backend's stable `error` code is
  trusted; the server's own message, `correlation_id`, portal HTML and any
  unexpected body are dropped.
- `wire.ts` — the backend's snake_case shapes, consumed only by adapters.
- `adapters/` — the wire-to-frontend mapping. Validates rather than casts and
  fails closed on anything it does not understand.
- `accounts.ts` — GET /accounts.
- `claims.ts` — GET /claims, always scoped to one account.

Only read endpoints are called. No state-changing request is made anywhere in
the application yet.
