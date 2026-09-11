import { useEffect, useMemo, useState } from "react";
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
type CategoryFilter = string | "ALL";

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
  const [category, setCategory] = useState<CategoryFilter>("ALL");

  // Filters belong to the account being looked at. Carrying a search from one
  // account into another would silently hide rows in the new queue and read
  // as "this account has almost nothing to do".
  useEffect(() => {
    setSearch("");
    setStatus("ALL");
    setCategory("ALL");
  }, [account.accountId]);

  const claims = query.data;
  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const claim of claims ?? []) {
      // A malformed duplicate on one claim must not inflate the badge.
      for (const label of new Set(claim.categories)) {
        counts.set(label, (counts.get(label) ?? 0) + 1);
      }
    }
    return [...counts.entries()].sort(([left], [right]) => left.localeCompare(right, "fr"));
  }, [claims]);
  const totalNotificationCount = categoryCounts.reduce((total, [, count]) => total + count, 0);

  useEffect(() => {
    if (category !== "ALL" && !categoryCounts.some(([label]) => label === category)) {
      setCategory("ALL");
    }
  }, [category, categoryCounts]);

  const visible = useMemo(() => {
    if (claims === undefined) return [];
    return claims.filter(
      (claim) =>
        (category === "ALL" || claim.categories.includes(category)) &&
        (status === "ALL" || claim.status === status) &&
        matchesSearch(claim, search),
    );
  }, [category, claims, search, status]);

  const isFiltered = search.length > 0 || status !== "ALL" || category !== "ALL";

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
            {categoryCounts.length > 0 ? (
              <div className={styles.categoryFilters} aria-label="Types de notifications">
                <CategoryButton
                  active={category === "ALL"}
                  count={totalNotificationCount}
                  label="Toutes les alertes"
                  onClick={() => setCategory("ALL")}
                />
                {categoryCounts.map(([label, count]) => (
                  <CategoryButton
                    active={category === label}
                    count={count}
                    key={label}
                    label={label}
                    onClick={() => setCategory(label)}
                  />
                ))}
              </div>
            ) : null}

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
              <ClaimList accountId={account.accountId} claims={visible} />
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

function CategoryButton({
  active,
  count,
  label,
  onClick,
}: {
  readonly active: boolean;
  readonly count: number;
  readonly label: string;
  readonly onClick: () => void;
}) {
  return (
    <button
      aria-label={`${label} — ${count} ${count === 1 ? "alerte" : "alertes"}`}
      aria-pressed={active}
      className={`${styles.categoryButton} ${active ? styles.categoryButtonActive : ""}`}
      onClick={onClick}
      type="button"
    >
      <span className={styles.bell} aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
        </svg>
      </span>
      <span className={styles.categoryLabel}>{label}</span>
      <span className={styles.categoryCount} aria-hidden="true">
        {count}
      </span>
    </button>
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
