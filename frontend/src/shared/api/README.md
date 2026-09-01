# api

The single place requests are made and errors are shaped. UI components never
call `fetch` directly.

STEP 1 contains `errors.ts` only: a pure normalizer with no request code, no
network access and no side effects. It maps a backend error `code` to a
sentence written for an employee, so raw server text, exception detail or
portal HTML can never reach the interface.
