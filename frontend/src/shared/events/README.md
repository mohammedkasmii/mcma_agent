# events

Reserved for the client of the backend's authenticated `/events` SSE stream:
connection handling, reconnection, the server `resync` event, and query
invalidation on relevant events.

Empty in STEP 1. There will be no second real-time transport and no polling
where the existing stream already answers the question.

This file exists so the directory is tracked by git, which does not record
empty directories.
