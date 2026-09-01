import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setCsrfCookie } from "../../test/apiMock";
import { SYNTHETIC_DOSSIER, WRITABLE_ACCOUNT_WIRE } from "../../test/fixtures";
import { newIdempotencyKey } from "@shared/utils/idempotency";
import { useAuthorizeExecution, useStartDryRun } from "./queries";

/**
 * A client that genuinely retries mutations.
 *
 * The production client does not retry, but relying on that to prevent a
 * duplicate automation would make the guarantee accidental. These tests turn
 * retry on deliberately: the key must survive it because it lives in the
 * mutation variables, not in the mutation function.
 */
function retryingWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: 1, retryDelay: 0 },
    },
  });
  return function Wrapper({ children }: { readonly children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

/** Fails the first request, succeeds on the second. */
function failThenSucceed(body: unknown) {
  let calls = 0;
  const stub = vi.fn((_url: string, _init?: RequestInit) => {
    calls += 1;
    const failing = calls === 1;
    return Promise.resolve({
      ok: !failing,
      status: failing ? 500 : 200,
      text: () =>
        Promise.resolve(
          JSON.stringify(
            failing
              ? { error: "INTERNAL_ERROR", message: "boom", correlation_id: "0" }
              : body,
          ),
        ),
    } as unknown as Response);
  });
  vi.stubGlobal("fetch", stub);
  return stub;
}

function keysSent(stub: { mock: { calls: unknown[][] } }): string[] {
  return stub.mock.calls.map(
    ([, init]) =>
      (JSON.parse((init as RequestInit).body as string) as { idempotency_key: string })
        .idempotency_key,
  );
}

describe("dry-run idempotency", () => {
  it("reuses one key across a retried attempt", async () => {
    setCsrfCookie();
    const stub = failThenSucceed({ job_id: "test-job-dry-1", status: "QUEUED" });
    const { result } = renderHook(() => useStartDryRun(), { wrapper: retryingWrapper() });

    result.current.mutate({
      accountId: WRITABLE_ACCOUNT_WIRE.account_id,
      typedInput: SYNTHETIC_DOSSIER,
      idempotencyKey: newIdempotencyKey(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = keysSent(stub);
    expect(keys).toHaveLength(2);
    // One attempt, one key: the backend deduplicates on it, so a second key
    // here would be a second dry run.
    expect(keys[0]).toBe(keys[1]);
  });

  it("uses a different key for a genuinely new attempt", async () => {
    setCsrfCookie();
    const stub = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify({ job_id: "j", status: "QUEUED" })),
      } as unknown as Response),
    );
    vi.stubGlobal("fetch", stub);
    const { result } = renderHook(() => useStartDryRun(), { wrapper: retryingWrapper() });

    const input = { accountId: WRITABLE_ACCOUNT_WIRE.account_id, typedInput: SYNTHETIC_DOSSIER };
    result.current.mutate({ ...input, idempotencyKey: newIdempotencyKey() });
    await waitFor(() => expect(stub).toHaveBeenCalledTimes(1));
    result.current.mutate({ ...input, idempotencyKey: newIdempotencyKey() });
    await waitFor(() => expect(stub).toHaveBeenCalledTimes(2));

    const keys = keysSent(stub);
    expect(keys[0]).not.toBe(keys[1]);
  });
});

describe("execution idempotency", () => {
  it("reuses one key across a retried authorization", async () => {
    setCsrfCookie();
    const stub = failThenSucceed({ job_id: "test-job-exec-1", status: "QUEUED" });
    const { result } = renderHook(() => useAuthorizeExecution(WRITABLE_ACCOUNT_WIRE.account_id, "test-job-dry-1"), {
      wrapper: retryingWrapper(),
    });

    result.current.mutate(newIdempotencyKey());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const keys = keysSent(stub);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
    // Both attempts targeted the same parent dry-run.
    for (const call of stub.mock.calls) {
      expect(call[0]).toBe("/jobs/test-job-dry-1/executions");
    }
  });
});
