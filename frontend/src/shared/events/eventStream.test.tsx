import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { EVENTS_PATH, openEventStream } from "./eventStream";
import { useEventStream } from "./useEventStream";

/**
 * A stub EventSource. jsdom has none, so the bridge takes a factory; this is
 * the seam the tests use rather than a fake state source in production code.
 */
class StubEventSource {
  static instances: StubEventSource[] = [];
  readonly listeners = new Map<string, Set<(event: MessageEvent) => void>>();
  closed = false;

  constructor(readonly url: string) {
    StubEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data?: string) {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data } as MessageEvent);
    }
  }
}

function stubFactory(url: string) {
  return new StubEventSource(url) as unknown as EventSource;
}

function reset() {
  StubEventSource.instances = [];
}

function noopHandlers() {
  return { onJobEvent: () => {}, onResync: () => {}, onConnected: () => {} };
}

describe("openEventStream", () => {
  it("connects to the same-origin events path", () => {
    reset();
    openEventStream(noopHandlers(), stubFactory);
    expect(StubEventSource.instances[0]?.url).toBe(EVENTS_PATH);
    expect(EVENTS_PATH.startsWith("/")).toBe(true);
    expect(EVENTS_PATH).not.toContain("://");
  });

  it("treats both real job event types as invalidation signals", () => {
    reset();
    const onJobEvent = vi.fn();
    openEventStream({ ...noopHandlers(), onJobEvent }, stubFactory);
    const source = StubEventSource.instances[0];

    source?.emit("JOB_CREATED", JSON.stringify({ job_id: "j", status: "QUEUED" }));
    source?.emit("JOB_STATUS_CHANGED", JSON.stringify({ job_id: "j", status: "WRITING" }));

    expect(onJobEvent).toHaveBeenCalledTimes(2);
  });

  it("routes resync separately", () => {
    reset();
    const onResync = vi.fn();
    const onJobEvent = vi.fn();
    openEventStream({ ...noopHandlers(), onJobEvent, onResync }, stubFactory);

    StubEventSource.instances[0]?.emit("resync", JSON.stringify({ cursor: 42 }));

    expect(onResync).toHaveBeenCalledTimes(1);
    expect(onJobEvent).not.toHaveBeenCalled();
  });

  it("survives malformed and unknown payloads without reading them", () => {
    reset();
    const onJobEvent = vi.fn();
    const onResync = vi.fn();
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    openEventStream({ ...noopHandlers(), onJobEvent, onResync }, stubFactory);
    const source = StubEventSource.instances[0];

    expect(() => {
      source?.emit("JOB_STATUS_CHANGED", "{not json");
      source?.emit("JOB_STATUS_CHANGED", undefined);
      source?.emit("resync", "<html>nope</html>");
      source?.emit("message", "anything");
      source?.emit("error");
    }).not.toThrow();

    // Still invalidates: "something happened, details unclear" means ask the
    // server, not ignore it.
    expect(onJobEvent).toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
  });

  it("treats every connection open as a catch-up point", () => {
    // A fresh stream starts at the backend's current event and replays
    // nothing earlier, so connecting is when missed work must be fetched.
    reset();
    const onConnected = vi.fn();
    openEventStream({ ...noopHandlers(), onConnected }, stubFactory);

    StubEventSource.instances[0]?.emit("open");
    expect(onConnected).toHaveBeenCalledTimes(1);

    // A browser-driven reconnect fires "open" again on the same instance.
    StubEventSource.instances[0]?.emit("open");
    expect(onConnected).toHaveBeenCalledTimes(2);
  });

  it("opens no retry timer of its own", () => {
    reset();
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const handle = openEventStream(noopHandlers(), stubFactory);

    StubEventSource.instances[0]?.emit("error");

    // Reconnection stays the browser's responsibility.
    expect(setIntervalSpy).not.toHaveBeenCalled();
    expect(setTimeoutSpy).not.toHaveBeenCalled();
    handle.close();
    setIntervalSpy.mockRestore();
    setTimeoutSpy.mockRestore();
  });

  it("closes the underlying connection", () => {
    reset();
    const handle = openEventStream(noopHandlers(), stubFactory);
    handle.close();
    expect(StubEventSource.instances[0]?.closed).toBe(true);
  });

  it("opens nothing when the environment has no EventSource", () => {
    // jsdom has none. The application still works from GET; nothing is faked.
    expect(typeof EventSource).toBe("undefined");
    const handle = openEventStream(noopHandlers());
    expect(() => handle.close()).not.toThrow();
  });
});

function Harness() {
  useEventStream(stubFactory);
  return <p>ready</p>;
}

function wrap(client: QueryClient, children: ReactNode) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useEventStream", () => {
  it("opens exactly one stream and closes it on unmount", () => {
    reset();
    const client = new QueryClient();
    const view = render(wrap(client, <Harness />));

    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(StubEventSource.instances).toHaveLength(1);

    view.rerender(wrap(client, <Harness />));
    expect(StubEventSource.instances).toHaveLength(1);

    view.unmount();
    expect(StubEventSource.instances[0]?.closed).toBe(true);
  });

  it("invalidates job caches on a job event, and does not write status itself", async () => {
    reset();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const setData = vi.spyOn(client, "setQueryData");
    render(wrap(client, <Harness />));

    StubEventSource.instances[0]?.emit(
      "JOB_STATUS_CHANGED",
      JSON.stringify({ job_id: "j", status: "HUMAN_CONFIRMED_COMPLETE" }),
    );

    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
    expect(keys).toContain(JSON.stringify(["jobs"]));
    expect(keys).toContain(JSON.stringify(["job"]));
    expect(keys).toContain(JSON.stringify(["job-plan"]));
    // The payload named a status. It was never written anywhere.
    expect(setData).not.toHaveBeenCalled();
  });

  it("invalidates every stale-able collection on resync", async () => {
    reset();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(wrap(client, <Harness />));

    StubEventSource.instances[0]?.emit("resync", JSON.stringify({ cursor: 7 }));

    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
    for (const prefix of ["accounts", "claims", "jobs", "job", "job-plan"]) {
      expect(keys).toContain(JSON.stringify([prefix]));
    }
  });

  it("catches up on connect and on every reconnect", async () => {
    reset();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(wrap(client, <Harness />));

    StubEventSource.instances[0]?.emit("open");
    await waitFor(() => expect(invalidate).toHaveBeenCalled());

    const keysAfterFirst = invalidate.mock.calls.map((call) =>
      JSON.stringify(call[0]?.queryKey),
    );
    for (const prefix of ["accounts", "claims", "jobs", "job", "job-plan"]) {
      expect(keysAfterFirst).toContain(JSON.stringify([prefix]));
    }

    const countAfterFirst = invalidate.mock.calls.length;
    // A reconnect is another point where events were missed.
    StubEventSource.instances[0]?.emit("open");
    await waitFor(() => expect(invalidate.mock.calls.length).toBeGreaterThan(countAfterFirst));
  });

  it("refreshes the global job collection when a job is created", async () => {
    reset();
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(wrap(client, <Harness />));

    StubEventSource.instances[0]?.emit(
      "JOB_CREATED",
      JSON.stringify({ job_id: "j", status: "QUEUED" }),
    );

    await waitFor(() => expect(invalidate).toHaveBeenCalled());
    const keys = invalidate.mock.calls.map((call) => JSON.stringify(call[0]?.queryKey));
    // ["jobs"] is the prefix of the global collection key ["jobs","global"].
    expect(keys).toContain(JSON.stringify(["jobs"]));
  });

  it("stores no cursor anywhere", () => {
    reset();
    const client = new QueryClient();
    render(wrap(client, <Harness />));
    StubEventSource.instances[0]?.emit("resync", JSON.stringify({ cursor: 99 }));

    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(window.location.href).not.toContain("cursor");
  });
});
