type ClassValue = string | false | null | undefined;

/**
 * Joins class names, dropping anything absent.
 *
 * CSS-module lookups are typed as possibly-undefined under
 * `noUncheckedIndexedAccess`, so this keeps the call sites free of `?? ""`
 * and prevents the string "undefined" ever reaching a class attribute.
 */
export function cx(...values: ClassValue[]): string {
  return values.filter((value): value is string => Boolean(value)).join(" ");
}
