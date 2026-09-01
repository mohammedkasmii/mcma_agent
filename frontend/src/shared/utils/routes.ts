/**
 * Every route path in one place.
 *
 * Account-scoped screens carry the account in the URL, so a reload or a
 * pasted link always restores the same account context. Job and claim
 * identifiers appear in the URL because they are opaque handles the backend
 * re-authorizes on every request — never dossier content, which stays out of
 * the address bar entirely.
 */

export const ROUTES = {
  overview: "/overview",
  accountWork: "/accounts/:accountId/work",
  accountClaim: "/accounts/:accountId/work/:claimPk",
  accountAgent: "/accounts/:accountId/agent",
  accountAgentJob: "/accounts/:accountId/agent/runs/:jobId",
} as const;

export function accountWorkPath(accountId: string): string {
  return `/accounts/${encodeURIComponent(accountId)}/work`;
}

export function accountClaimPath(accountId: string, claimPk: string): string {
  return `${accountWorkPath(accountId)}/${encodeURIComponent(claimPk)}`;
}

export function accountAgentPath(accountId: string): string {
  return `/accounts/${encodeURIComponent(accountId)}/agent`;
}

export function accountAgentJobPath(accountId: string, jobId: string): string {
  return `${accountAgentPath(accountId)}/runs/${encodeURIComponent(jobId)}`;
}
