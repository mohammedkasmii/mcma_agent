import { vi } from "vitest";
import type { Mock } from "vitest";
import { mockRoutes } from "./apiMock";
import type { RouteHandler } from "./apiMock";
import { TEST_ACCOUNTS_WIRE } from "./fixtures";

/** GET /auth/me body, in the wire shape the backend sends. */
export function meWire(overrides: Record<string, unknown> = {}) {
  return {
    user_id: "user-1",
    username: "admin",
    role: "admin",
    permissions: [],
    account_ids: [],
    local_single_user: false,
    ...overrides,
  };
}

export const GOOD_PASSWORD = "correct-horse-battery";

export interface AuthBackend {
  readonly stub: Mock;
  /** The server forgets the session (expiry, or a restart wiping memory). */
  expire(): void;
  isSignedIn(): boolean;
  urls(): string[];
  calls(prefix: string): number;
}

/**
 * A stateful backend: /auth/me and every other route answer 401 while no
 * session exists, exactly as the real server does after a restart.
 */
export function mockAuthBackend(
  options: {
    readonly signedIn: boolean;
    readonly me?: Record<string, unknown>;
    readonly extra?: readonly RouteHandler[];
  },
): AuthBackend {
  let signedIn = options.signedIn;
  const unauth = { error: "UNAUTHENTICATED", message: "x", correlation_id: "0" };
  const stub = mockRoutes([
    {
      match: (url) => url === "/auth/me",
      status: () => (signedIn ? 200 : 401),
      body: () => (signedIn ? meWire(options.me) : unauth),
    },
    {
      match: (url, init) => url === "/auth/login" && init.method === "POST",
      status: (_url: string, init: RequestInit) =>
        (JSON.parse(String(init.body)) as { password: string }).password === GOOD_PASSWORD
          ? 200
          : 401,
      body: (_url: string, init: RequestInit) => {
        const ok = (JSON.parse(String(init.body)) as { password: string }).password === GOOD_PASSWORD;
        if (ok) signedIn = true;
        return ok
          ? { user_id: "user-1", username: "admin", role: "admin", csrf_token: "t" }
          : { error: "INVALID_CREDENTIALS", message: "x", correlation_id: "0" };
      },
    },
    {
      match: (url, init) => url === "/auth/logout" && init.method === "POST",
      body: () => {
        signedIn = false;
        return { status: "logged_out" };
      },
    },
    { match: () => !signedIn, status: 401, body: unauth },
    ...(options.extra ?? []),
    { match: (url) => url.startsWith("/accounts"), body: { accounts: TEST_ACCOUNTS_WIRE } },
    { match: (url) => url.startsWith("/claims"), body: { claims: [] } },
    { match: (url) => url.startsWith("/jobs"), body: { jobs: [] } },
  ]);
  return {
    stub,
    expire: () => {
      signedIn = false;
    },
    isSignedIn: () => signedIn,
    urls: () => stub.mock.calls.map(([url]) => url as string),
    calls: (prefix) =>
      stub.mock.calls.filter(([url]) => (url as string).startsWith(prefix)).length,
  };
}

export class CountingEventSource {
  static live = 0;
  static opened = 0;
  closed = false;
  constructor(readonly url: string) {
    CountingEventSource.live += 1;
    CountingEventSource.opened += 1;
  }
  addEventListener() {}
  close() {
    if (!this.closed) {
      this.closed = true;
      CountingEventSource.live -= 1;
    }
  }
}

export function installEventSourceCounter(): typeof CountingEventSource {
  CountingEventSource.live = 0;
  CountingEventSource.opened = 0;
  vi.stubGlobal("EventSource", CountingEventSource);
  return CountingEventSource;
}

/** An EventSource whose events the test fires by hand. */
export class ControllableEventSource {
  static instances: ControllableEventSource[] = [];
  static live = 0;
  readyState = 1;
  closed = false;
  private readonly listeners = new Map<string, Array<() => void>>();
  constructor(readonly url: string) {
    ControllableEventSource.instances.push(this);
    ControllableEventSource.live += 1;
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    if (!this.closed) {
      this.closed = true;
      this.readyState = 2;
      ControllableEventSource.live -= 1;
    }
  }
  /** Fires an event; `closed` mimics the browser giving up (readyState CLOSED). */
  emit(type: string, options: { closed?: boolean } = {}) {
    if (options.closed === true) this.readyState = 2;
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
}

export function installControllableEventSource(): typeof ControllableEventSource {
  ControllableEventSource.instances = [];
  ControllableEventSource.live = 0;
  vi.stubGlobal("EventSource", ControllableEventSource);
  return ControllableEventSource;
}
