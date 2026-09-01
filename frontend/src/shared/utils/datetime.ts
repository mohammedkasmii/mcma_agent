/**
 * Timestamp formatting.
 *
 * The backend stores and returns ISO-8601 UTC strings. Those are correct but
 * unreadable at a glance, so they are formatted once, here, in French and in
 * the browser's own timezone — the employee's local time is the only one they
 * can act on.
 *
 * Nothing is invented: an absent timestamp stays absent, and a value that is
 * not a parseable instant is shown verbatim rather than replaced by a
 * plausible-looking date.
 */

const FORMATTER = new Intl.DateTimeFormat("fr-FR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatTimestamp(value: string | null): string | null {
  if (value === null || value.length === 0) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return FORMATTER.format(parsed);
}
