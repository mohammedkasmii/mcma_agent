import { afterEach, describe, expect, it, vi } from "vitest";
import { newIdempotencyKey } from "./idempotency";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("newIdempotencyKey", () => {
  it("produces a distinct key each time", () => {
    const keys = new Set(Array.from({ length: 50 }, newIdempotencyKey));
    expect(keys.size).toBe(50);
  });

  it("prefers crypto.randomUUID when the context provides it", () => {
    const randomUUID = vi.fn(() => "11111111-2222-3333-4444-555555555555");
    vi.stubGlobal("crypto", { randomUUID, getRandomValues: () => expect.unreachable() });
    expect(newIdempotencyKey()).toBe("11111111-2222-3333-4444-555555555555");
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });

  it("never falls back to Math.random", () => {
    // Math.random is not a source a deduplication key may depend on.
    const spy = vi.spyOn(Math, "random");
    newIdempotencyKey();
    vi.stubGlobal("crypto", {
      getRandomValues: (array: Uint8Array) => {
        array.fill(3);
        return array;
      },
    });
    newIdempotencyKey();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("falls back to getRandomValues outside a secure context", () => {
    // randomUUID is undefined on plain http; the agent must still work.
    vi.stubGlobal("crypto", {
      getRandomValues: (array: Uint8Array) => {
        array.fill(7);
        return array;
      },
    });
    expect(newIdempotencyKey()).toBe("07".repeat(16));
  });
});
