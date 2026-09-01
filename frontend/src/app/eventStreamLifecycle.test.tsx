import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAppAt } from "../test/renderApp";
import { mockRoutes } from "../test/apiMock";
import {
  EXECUTION_JOB_WIRE,
  SECOND_WRITABLE_ACCOUNT_WIRE,
  TEST_ACCOUNTS_WIRE,
  WRITABLE_ACCOUNT_WIRE,
} from "../test/fixtures";

/**
 * The stream is mounted by AppShell, which the router keeps mounted across
 * every navigation. These tests drive the real application through the real
 * router and count connections, rather than re-rendering one hook.
 *
 * jsdom has no EventSource, so a stub is installed globally — the production
 * code path (its own default factory) is what gets exercised.
 */
class CountingEventSource {
  static live = 0;
  static opened = 0;
  static urls: string[] = [];
  static inits: (EventSourceInit | undefined)[] = [];
  closed = false;

  constructor(
    readonly url: string,
    init?: EventSourceInit,
  ) {
    CountingEventSource.live += 1;
    CountingEventSource.opened += 1;
    CountingEventSource.urls.push(url);
    CountingEventSource.inits.push(init);
  }

  addEventListener() {}

  close() {
    if (!this.closed) {
      this.closed = true;
      CountingEventSource.live -= 1;
    }
  }
}

function installStub() {
  CountingEventSource.live = 0;
  CountingEventSource.opened = 0;
  CountingEventSource.urls = [];
  CountingEventSource.inits = [];
  vi.stubGlobal("EventSource", CountingEventSource);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function backend() {
  return mockRoutes([
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [EXECUTION_JOB_WIRE] } },
  ]);
}

describe("application event stream lifecycle", () => {
  it("establishes exactly one stream for the application", async () => {
    installStub();
    backend();
    renderAppAt("/overview");

    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(CountingEventSource.live).toBe(1);
    expect(CountingEventSource.opened).toBe(1);
  });

  it("does not open a second stream when navigating between workspaces", async () => {
    installStub();
    backend();
    const user = userEvent.setup();
    renderAppAt("/overview");

    await screen.findByRole("heading", { name: "Vue d'ensemble" });
    expect(CountingEventSource.opened).toBe(1);

    // Navigate through the rail into an account workspace...
    await user.click(await screen.findByRole("link", { name: /MCMA • ZONE-A/ }));
    await screen.findByRole("heading", { name: "File de travail" });

    // ...and on to a different account.
    await user.click(screen.getByRole("link", { name: /MCMA • ZONE-C/ }));
    await waitFor(() =>
      expect(screen.getAllByRole("heading", { name: "File de travail" }).length).toBeGreaterThan(0),
    );

    // AppShell never unmounted, so the same single stream carried through.
    expect(CountingEventSource.opened).toBe(1);
    expect(CountingEventSource.live).toBe(1);
  });

  it("closes the stream when the application unmounts", async () => {
    installStub();
    backend();
    const view = renderAppAt(`/accounts/${WRITABLE_ACCOUNT_WIRE.account_id}/work`);

    await screen.findByRole("heading", { name: "File de travail" });
    expect(CountingEventSource.live).toBe(1);

    view.unmount();
    expect(CountingEventSource.live).toBe(0);
  });

  it("connects to the same-origin events path with credentials", async () => {
    installStub();
    backend();
    renderAppAt(`/accounts/${SECOND_WRITABLE_ACCOUNT_WIRE.account_id}/work`);

    await screen.findByRole("heading", { name: "File de travail" });
    expect(CountingEventSource.urls).toEqual(["/events"]);
    // Root-relative: never an absolute URL to another origin.
    expect(CountingEventSource.urls[0]).not.toContain("://");
    expect(CountingEventSource.inits[0]?.withCredentials).toBe(true);
  });
});
