import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { openEventStream } from "./eventStream";
import type { EventStreamHandle } from "./eventStream";

/**
 * Mounts the one application-level event stream.
 *
 * Called from the shell, which mounts once and survives every navigation, so
 * moving between screens never opens a second connection. The stream closes
 * when the shell unmounts.
 *
 * Invalidation is deliberately coarse. Query keys all start with a stable
 * first segment, so invalidating by prefix reaches every account's entry
 * without this module needing to know which account or job an event concerned
 * — information the payload may not carry, and which it would be unwise to
 * trust if it did.
 *
 * Connecting is itself an invalidation point. A fresh stream starts at the
 * backend's current event and replays nothing earlier, so anything that
 * happened while there was no connection has to be caught by asking the
 * server, not by waiting for an event that will never arrive.
 */
/** Every server-state prefix an outage could have left behind. */
const EVERYTHING_STALEABLE = ["accounts", "claims", "jobs", "job", "job-plan"] as const;

export type SessionCheckResult = "ok" | "expired" | "unreachable";

export function useEventStream(
  factory?: Parameters<typeof openEventStream>[1],
  onSessionCheck?: () => Promise<SessionCheckResult>,
): void {
  const queryClient = useQueryClient();
  const checkRef = useRef(onSessionCheck);
  checkRef.current = onSessionCheck;

  useEffect(() => {
    let disposed = false;
    // Identifies the source currently open. A check that outlives its source
    // (a burst of errors on one connection) must not reopen a second one.
    let generation = 0;
    let handle: EventStreamHandle | null = null;

    function invalidate(prefixes: readonly string[]) {
      for (const prefix of prefixes) {
        void queryClient.invalidateQueries({ queryKey: [prefix] });
      }
    }

    async function check(fromGeneration: number, closed: boolean) {
      const run = checkRef.current;
      if (run === undefined) return;
      const result = await run();
      if (disposed || fromGeneration !== generation) return;
      // The session is fine but the browser gave up on the stream: reopen it,
      // closing the old source first so two never live at once.
      if (result === "ok" && closed) open();
    }

    function open() {
      handle?.close();
      generation += 1;
      const mine = generation;
      handle = openEventStream(
      {
        // A job changed somewhere: refresh the collections and details that
        // could describe it. The GET that follows is what decides the state.
        onJobEvent: () => invalidate(["jobs", "job", "job-plan"]),
        // A background notification poll ran for some account. Both the
        // per-account summaries (rail badges, overview counts, last refresh)
        // and the claim lists are derived from what it wrote, so both are
        // asked again. Without this, a poll that arrived while the employee
        // was looking at the screen stayed invisible until they navigated:
        // the stream carried job events only, and no query polls on a timer.
        onNotificationEvent: () => invalidate(["accounts", "claims"]),
        // The cursor was too stale to replay, so anything may have moved on.
        onResync: () => invalidate(EVERYTHING_STALEABLE),
        // Same treatment on connect and reconnect: whatever was emitted while
        // the stream was down was not replayed to us.
        onConnected: () => invalidate(EVERYTHING_STALEABLE),
        onError: (closed) => void check(mine, closed),
        onSessionEnded: () => void check(mine, true),
      },
      factory,
    );
    }

    open();

    return () => {
      disposed = true;
      handle?.close();
    };
    // The query client is stable for the life of the application; this effect
    // must run exactly once so only one connection ever exists.
  }, [queryClient, factory]);
}
