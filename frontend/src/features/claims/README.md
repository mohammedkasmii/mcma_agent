# claims

Reserved for the claim record surface: claim detail, employee tracking status
and notes.

Empty in STEP 1. The backend statuses are fixed and must be used exactly as
the API defines them (`NEW`, `IN_PROGRESS`, `WAITING`, `DONE`,
`NOT_APPLICABLE`); no other status value is ever sent.

This file exists so the directory is tracked by git, which does not record
empty directories.
