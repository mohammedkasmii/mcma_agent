import { useEffect } from "react";
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

export function useEventStream(factory?: Parameters<typeof openEventStream>[1]): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    function invalidate(prefixes: readonly string[]) {
      for (const prefix of prefixes) {
        void queryClient.invalidateQueries({ queryKey: [prefix] });
      }
    }

    const handle: EventStreamHandle = openEventStream(
      {
        // A job changed somewhere: refresh the collections and details that
        // could describe it. The GET that follows is what decides the state.
        onJobEvent: () => invalidate(["jobs", "job", "job-plan"]),
        // The cursor was too stale to replay, so anything may have moved on.
        onResync: () => invalidate(EVERYTHING_STALEABLE),
        // Same treatment on connect and reconnect: whatever was emitted while
        // the stream was down was not replayed to us.
        onConnected: () => invalidate(EVERYTHING_STALEABLE),
      },
      factory,
    );

    return () => {
      handle.close();
    };
    // The query client is stable for the life of the application; this effect
    // must run exactly once so only one connection ever exists.
  }, [queryClient, factory]);
}
