/**
 * The single employee-facing error shape.
 *
 * Server exception text, portal HTML and stack traces never reach the UI:
 * everything the interface renders comes through this normalized record,
 * whose `message` is written for an employee, not for a log.
 */
export interface ApiError {
  /** HTTP status, or 0 when the request never reached the server. */
  readonly status: number;
  /** Stable machine code from the backend, or a local fallback code. */
  readonly code: string;
  /** Short employee-facing sentence. Safe to render as text. */
  readonly message: string;
}
