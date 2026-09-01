import { describe, expect, it } from "vitest";
import { resolveSameOriginPath } from "./paths";

// jsdom serves these tests from a fixed origin; every case below is resolved
// against it. No request is made — this is pure string-to-URL resolution.

describe("resolveSameOriginPath", () => {
  it("accepts the API paths this application uses", () => {
    expect(resolveSameOriginPath("/accounts")).toBe("/accounts");
    expect(resolveSameOriginPath("/claims/123")).toBe("/claims/123");
    expect(resolveSameOriginPath("/jobs/abc/plan")).toBe("/jobs/abc/plan");
  });

  it("keeps a query string", () => {
    expect(resolveSameOriginPath("/claims?account_id=x")).toBe("/claims?account_id=x");
  });

  it("rejects a protocol-relative path", () => {
    expect(resolveSameOriginPath("//example.invalid")).toBeNull();
    expect(resolveSameOriginPath("//example.invalid/accounts")).toBeNull();
  });

  it("rejects backslash normalization tricks", () => {
    // The URL parser normalizes backslashes to slashes for HTTP URLs, so
    // these resolve to another host despite starting with "/".
    expect(resolveSameOriginPath("/\\example.invalid")).toBeNull();
    expect(resolveSameOriginPath("/\\/example.invalid")).toBeNull();
    expect(resolveSameOriginPath("\\\\example.invalid")).toBeNull();
  });

  it("rejects whitespace and control-character tricks", () => {
    // Tabs and newlines are stripped during parsing, which would uncover a
    // protocol-relative prefix.
    expect(resolveSameOriginPath("/\t/example.invalid")).toBeNull();
    expect(resolveSameOriginPath("/\n/example.invalid")).toBeNull();
    expect(resolveSameOriginPath("/\r/example.invalid")).toBeNull();
    expect(resolveSameOriginPath("/ /example.invalid")).toBeNull();
    expect(resolveSameOriginPath("/\u0000accounts")).toBeNull();
  });

  it("rejects absolute URLs", () => {
    expect(resolveSameOriginPath("https://example.invalid/accounts")).toBeNull();
    expect(resolveSameOriginPath("http://example.invalid/accounts")).toBeNull();
    expect(resolveSameOriginPath("javascript:alert(1)")).toBeNull();
    expect(resolveSameOriginPath("data:text/html,x")).toBeNull();
  });

  it("rejects an absolute URL naming this very origin", () => {
    // Correct today, but it would let an absolute URL through the one check
    // that keeps every other host out. Paths stay root-relative.
    expect(resolveSameOriginPath(`${window.location.origin}/accounts`)).toBeNull();
  });

  it("rejects a path that is not root-relative", () => {
    expect(resolveSameOriginPath("accounts")).toBeNull();
    expect(resolveSameOriginPath("../accounts")).toBeNull();
    expect(resolveSameOriginPath("")).toBeNull();
  });

  it("normalizes traversal that stays on this origin", () => {
    expect(resolveSameOriginPath("/jobs/../accounts")).toBe("/accounts");
  });
});
