/**
 * The application's single connection to the backend's SSE stream.
 *
 * An event is an INVALIDATION SIGNAL, never state. Nothing here ever writes a
 * status into a cache: an event says "something about this changed", the
 * affected TanStack queries are invalidated, and the authoritative GET decides
 * what is true. A payload that claimed a status could otherwise move the
 * interface ahead of — or behind — the backend.
 *
 * The cursor is not persisted anywhere, and Last-Event-ID alone does not make
 * reconnection lossless. The browser only sends that header once it has
 * actually received an event id, and mcma/app/sse.py starts a connection with
 * no header at the CURRENT latest event, replaying nothing before it. So a
 * transition emitted between the initial GET and the moment the stream
 * establishes would never be delivered — and with polling gone, the interface
 * would sit on a stale status indefinitely.
 *
 * That is why every `open` is treated as a catch-up point: connecting, or
 * reconnecting, triggers the same conservative invalidation as `resync`. The
 * refetch that follows is what closes the gap, not the stream.
 */

/** Event types the backend's outbox actually emits, plus the SSE control event. */
export const JOB_EVENT_TYPES = ["JOB_CREATED", "JOB_STATUS_CHANGED"] as const;
export const RESYNC_EVENT_TYPE = "resync";

export type EventStreamHandlers = {
  /** A job somewhere changed. Refresh job collections and job details. */
  readonly onJobEvent: () => void;
  /** The cursor was too old to replay: everything may be stale. */
  readonly onResync: () => void;
  /**
   * The connection just opened, initially or after a reconnect. Anything
   * emitted while there was no stream was never delivered, so this is a
   * catch-up point, not a lifecycle notification.
   */
  readonly onConnected: () => void;
};

export interface EventStreamHandle {
  close(): void;
}

/** Same-origin, matching the backend route. Never an absolute URL. */
export const EVENTS_PATH = "/events";

export type EventSourceFactory = (path: string) => EventSource;

const defaultFactory: EventSourceFactory = (path) =>
  new EventSource(path, { withCredentials: true });

/** Does nothing and says so. Never a source of invented state. */
const NO_STREAM: EventStreamHandle = { close: () => {} };

/**
 * Opens the stream and wires the two handler kinds.
 *
 * Malformed or unknown payloads are not parsed for meaning and never
 * rendered. A job event whose data cannot be read still invalidates: the
 * conservative reaction to "something happened, details unclear" is to go ask
 * the server, not to ignore it.
 *
 * No payload is logged. The outbox is documented as PII-free, but that is the
 * backend's guarantee to keep, not a reason for this layer to print it.
 */
export function openEventStream(
  handlers: EventStreamHandlers,
  factory?: EventSourceFactory,
): EventStreamHandle {
  // No EventSource in this environment (jsdom, for one). The application
  // still works: every screen loads its state from an authoritative GET, and
  // only live refresh is lost. Nothing is faked to cover the gap.
  if (factory === undefined && typeof EventSource === "undefined") {
    return NO_STREAM;
  }
  const source = (factory ?? defaultFactory)(EVENTS_PATH);

  for (const type of JOB_EVENT_TYPES) {
    source.addEventListener(type, () => {
      handlers.onJobEvent();
    });
  }

  source.addEventListener(RESYNC_EVENT_TYPE, () => {
    handlers.onResync();
  });

  // Fires on the first successful connection and on every browser-driven
  // reconnect. Both are moments where events may have been missed.
  source.addEventListener("open", () => {
    handlers.onConnected();
  });

  // An unnamed message is not something this application knows how to act on
  // precisely, so it is treated as "go and check" rather than ignored.
  source.addEventListener("message", () => {
    handlers.onJobEvent();
  });

  // Reconnection stays the browser's job. A custom retry loop here would
  // fight it and could open a second connection; the catch-up happens on the
  // "open" that follows, not on a timer.
  source.addEventListener("error", () => {});

  return {
    close() {
      source.close();
    },
  };
}
