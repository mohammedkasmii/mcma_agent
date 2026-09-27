import { describe, expect, it } from "vitest";
import { safeRedirectPath } from "./safeRedirect";

describe("safeRedirectPath", () => {
  it.each([
    ["/overview", "/overview"],
    ["/accounts/a1/work", "/accounts/a1/work"],
    ["/accounts/a1/work?status=new", "/accounts/a1/work?status=new"],
    ["/administration/users", "/administration/users"],
  ])("keeps the internal path %s", (input, expected) => {
    expect(safeRedirectPath(input)).toBe(expected);
  });

  it.each([
    "//evil.example",
    "//evil.example/path",
    "/\\evil.example",
    "\\\\evil.example",
    "/\t/evil.example",
    "/a\nb",
    "https://evil.example",
    "javascript:alert(1)",
    "evil",
    "",
    "/login",
    "/login?next=/x",
    "/login/",
    undefined,
    null,
    42,
    { from: "/x" },
  ])("falls back to the overview for %j", (input) => {
    expect(safeRedirectPath(input)).toBe("/overview");
  });
});
