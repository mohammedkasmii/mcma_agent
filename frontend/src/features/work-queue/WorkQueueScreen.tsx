import { useMemo, useState } from "react";
import type { Claim, ClaimStatus, PortalAccount } from "@shared/types";
import { CLAIM_STATUSES } from "@shared/types";
import { AccountWorkspaceHeader } from "@features/accounts/AccountWorkspaceHeader";
import { EmptyState, Panel, Skeleton } from "@shared/ui";
import { toApiError } from "@features/accounts/queries";
import { claimStatusLabel } from "@shared/utils/claimStatus";
import { ClaimList } from "./ClaimList";
import { useClaimsQuery } from "./queries";
import styles from "./WorkQueueScreen.module.css";

interface WorkQueueScreenProps {
  /** Resolved by the account route guard before this screen mounts. */
  readonly account: PortalAccount;
}

type StatusFilter = ClaimStatus | "ALL";

/** Local narrowing over rows already on screen. No backend search exists. */
function matchesSearch(claim: Claim, needle: string): boolean {
  if (needle.length === 0) return true;
  const haystack = [claim.reference, claim.insured, claim.matricule, claim.police]
    .filter((value): value is string => value !== null)
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle.toLowerCase());
}

/**
 * The claims an employee works through for one portal account.
 *
 * Available for every account, including read-only ones: "Lecture seule"
 * describes what the automation may do to a portal account, not whether its
 * work queue can be read.
 *
 * Read-only in a second sense for now — recording a status or a note is not
 * built yet — so this screen shows no tracking controls rather than showing
 * ones that would do nothing.
 */
export function WorkQueueScreen({ account }: WorkQueueScreenProps) {
  const query = useClaimsQuery(account.accountId);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("ALL");

  const claims = query.data;
  const visible = useMemo(() => {
    if (claims === undefined) return [];
    return claims.filter(
      (claim) => (status === "ALL" || claim.status === status) && matchesSearch(claim, search),
    );
  }, [claims, search, status]);

  const isFiltered = search.length > 0 || status !== "ALL";

  return (
    <div className="u-stack-5">
      <AccountWorkspaceHeader title="File de travail" resolution={{ status: "resolved", account }} />

      <Panel
        title="Sinistres"
        description="Les sinistres remontés par le portail pour ce compte."
      >
        {query.isPending ? <LoadingRows /> : null}

        {query.isError ? (
          <EmptyState title="Impossible de charger la file de travail">
            {toApiError(query.error).message}
          </EmptyState>
        ) : null}

        {query.isSuccess && claims !== undefined && claims.length === 0 ? (
          <EmptyState title="Aucun sinistre dans cette file">
            Ce compte n'a actuellement aucun sinistre à traiter.
          </EmptyState>
        ) : null}

        {query.isSuccess && claims !== undefined && claims.length > 0 ? (
          <div className="u-stack-4">
            <div className={styles.filters}>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Rechercher</span>
                <input
                  className={styles.input}
                  type="search"
                  value={search}
                  placeholder="Référence, assuré, immatriculation, police"
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>Suivi</span>
                <select
                  className={styles.input}
                  value={status}
                  onChange={(event) => setStatus(event.target.value as StatusFilter)}
                >
                  <option value="ALL">Tous</option>
                  {CLAIM_STATUSES.map((value) => (
                    <option key={value} value={value}>
                      {claimStatusLabel(value)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {visible.length === 0 ? (
              <EmptyState title="Aucun sinistre ne correspond">
                Élargissez la recherche ou revenez à tous les suivis.
              </EmptyState>
            ) : (
              <ClaimList claims={visible} />
            )}

            {isFiltered ? (
              <p className="t-meta">
                {visible.length} sur {claims.length} sinistres affichés
              </p>
            ) : null}
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

function LoadingRows() {
  return (
    <div className={styles.loading} aria-busy="true">
      <p className="u-visually-hidden">Chargement des sinistres</p>
      {[0, 1, 2, 3].map((slot) => (
        <div className={styles.loadingRow} key={slot}>
          <Skeleton size="md" />
          <Skeleton size="lg" />
          <Skeleton size="sm" />
        </div>
      ))}
    </div>
  );
}
