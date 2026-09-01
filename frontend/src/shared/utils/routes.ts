/**
 * Every route path in one place.
 *
 * Account-scoped screens carry the account in the URL, so a reload or a
 * pasted link always restores the same account context.
 */

export const ROUTES = {
  overview: "/overview",
  accountWork: "/accounts/:accountId/work",
  accountAgent: "/accounts/:accountId/agent",
} as const;

export function accountWorkPath(accountId: string): string {
  return `/accounts/${encodeURIComponent(accountId)}/work`;
}

export function accountAgentPath(accountId: string): string {
  return `/accounts/${encodeURIComponent(accountId)}/agent`;
}
