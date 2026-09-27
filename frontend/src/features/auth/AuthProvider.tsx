import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { AuthSession } from "@shared/types";
import { fetchSession, login as loginRequest, logout as logoutRequest } from "@shared/api/auth";
import { ApiRequestError, setUnauthorizedListener } from "@shared/api/client";

/**
 * The one owner of "who is signed in".
 *
 * Authentication state lives in React memory only. Nothing about it -- no
 * password, token or flag -- is written to localStorage or sessionStorage;
 * the HttpOnly session cookie is the only durable authority and the server
 * re-checks it on every request.
 */
export type AuthState =
  | { readonly status: "loading" }
  | { readonly status: "unavailable" }
  | { readonly status: "authenticated"; readonly session: AuthSession }
  /** reason: "expired" shows the session-expired notice; "logout" carries no return path. */
  | { readonly status: "unauthenticated"; readonly reason: "initial" | "expired" | "logout" };

export interface AuthContextValue {
  readonly state: AuthState;
  /** Throws ApiRequestError on failure; the caller maps the code. */
  login(username: string, password: string): Promise<void>;
  /** Idempotent: repeated calls while one is in flight do nothing. */
  logout(): Promise<void>;
  /** Re-runs the initial session probe after "server unreachable". */
  retry(): void;
  /**
   * Asks the server (GET /auth/me) whether the session still exists. Called
   * when the event stream errors. Single-flight and rate-limited; a call
   * suppressed by the cooldown is not lost but answered by one trailing check.
   * A 401 performs the normal expired-session transition; a network failure
   * is "unreachable" and changes nothing.
   */
  recheckSession(): Promise<SessionCheckResult>;
}

export type SessionCheckResult = "ok" | "expired" | "unreachable";

/** Minimum gap between two session rechecks. */
export const RECHECK_COOLDOWN_MS = 5000;

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

interface AuthProviderProps {
  readonly children: ReactNode;
  /** Tests start authenticated without a probe. Production never passes this. */
  readonly initialSession?: AuthSession;
  /** Tests shorten the cooldown; production uses RECHECK_COOLDOWN_MS. */
  readonly recheckCooldownMs?: number;
}

export function AuthProvider({
  children,
  initialSession,
  recheckCooldownMs = RECHECK_COOLDOWN_MS,
}: AuthProviderProps) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>(
    initialSession === undefined
      ? { status: "loading" }
      : { status: "authenticated", session: initialSession },
  );
  const [probeNonce, setProbeNonce] = useState(0);
  const loggingOut = useRef(false);
  const statusRef = useRef<AuthState["status"]>(state.status);
  statusRef.current = state.status;
  const inflight = useRef<Promise<SessionCheckResult> | null>(null);
  const lastCheckAt = useRef(Number.NEGATIVE_INFINITY);
  const trailing = useRef<{ promise: Promise<SessionCheckResult>; timer: number } | null>(null);

  const expire = useCallback(() => {
    if (loggingOut.current) return;
    setState((previous) =>
      previous.status === "authenticated"
        ? { status: "unauthenticated", reason: "expired" }
        : previous,
    );
  }, []);

  // Initial probe. Skipped when the state was seeded.
  useEffect(() => {
    if (initialSession !== undefined && probeNonce === 0) return;
    const controller = new AbortController();
    setState({ status: "loading" });
    fetchSession(controller.signal).then(
      (session) => {
        if (!controller.signal.aborted) setState({ status: "authenticated", session });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiRequestError && error.apiError.status === 401) {
          setState({ status: "unauthenticated", reason: "initial" });
        } else {
          setState({ status: "unavailable" });
        }
      },
    );
    return () => controller.abort();
  }, [initialSession, probeNonce]);

  // Global 401 -> one session-expired transition. The functional update makes
  // a burst of concurrent 401s collapse into a single transition, and a 401
  // during logout is ignored so logout can never loop back through here.
  useEffect(() => {
    return setUnauthorizedListener(expire);
  }, [expire]);

  // Whenever the user is signed out, nothing they could see may stay cached.
  // The shell (streams, queries) has already unmounted by the time this runs.
  const status = state.status;
  useEffect(() => {
    if (status === "unauthenticated") {
      void queryClient.cancelQueries();
      queryClient.clear();
    }
  }, [status, queryClient]);

  const login = useCallback(async (username: string, password: string) => {
    await loginRequest(username, password);
    const session = await fetchSession();
    loggingOut.current = false;
    setState({ status: "authenticated", session });
  }, []);

  const logout = useCallback(async () => {
    if (loggingOut.current) return;
    loggingOut.current = true;
    try {
      await logoutRequest();
    } catch {
      // Whatever the server said, this browser is done with the session.
    }
    setState({ status: "unauthenticated", reason: "logout" });
  }, []);

  const runCheck = useCallback((): Promise<SessionCheckResult> => {
    lastCheckAt.current = Date.now();
    const promise = fetchSession().then(
      (): SessionCheckResult => "ok",
      (error: unknown): SessionCheckResult => {
        if (error instanceof ApiRequestError && error.apiError.status === 401) {
          expire();
          return "expired";
        }
        return "unreachable";
      },
    );
    const tracked: Promise<SessionCheckResult> = promise.finally(() => {
      if (inflight.current === tracked) inflight.current = null;
    });
    inflight.current = tracked;
    return tracked;
  }, [expire]);

  const recheckSession = useCallback((): Promise<SessionCheckResult> => {
    if (statusRef.current !== "authenticated" || loggingOut.current) {
      return Promise.resolve("ok");
    }
    if (trailing.current !== null) return trailing.current.promise;
    const wait = lastCheckAt.current + recheckCooldownMs - Date.now();
    if (inflight.current === null && wait <= 0) return runCheck();

    // Suppressed: exactly one trailing check at the end of the cooldown, so
    // the last error (possibly the one carrying the 401) is never dropped.
    const delay = Math.max(wait, 0);
    let resolveTrailing!: (result: SessionCheckResult) => void;
    const promise = new Promise<SessionCheckResult>((resolve) => {
      resolveTrailing = resolve;
    });
    const timer = window.setTimeout(() => {
      trailing.current = null;
      if (statusRef.current !== "authenticated" || loggingOut.current) {
        resolveTrailing("ok");
        return;
      }
      // Never two probes at once: join one that is somehow still running.
      void (inflight.current ?? runCheck()).then(resolveTrailing);
    }, delay);
    trailing.current = { promise, timer };
    return promise;
  }, [recheckCooldownMs, runCheck]);

  useEffect(
    () => () => {
      if (trailing.current !== null) window.clearTimeout(trailing.current.timer);
    },
    [],
  );

  const retry = useCallback(() => setProbeNonce((n) => n + 1), []);

  const value = useMemo(
    () => ({ state, login, logout, retry, recheckSession }),
    [state, login, logout, retry, recheckSession],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
