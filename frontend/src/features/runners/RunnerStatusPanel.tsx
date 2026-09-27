import { Panel } from "@shared/ui";
import { OWN_RUNNER_STATUS_SENTENCES, sessionSentence } from "@shared/utils/runnerLabels";
import { useOwnRunnerStatusQuery } from "./queries";

/**
 * Status only. Nothing on the agent screen is enabled or disabled from this:
 * the backend decides whether a job can run.
 */
export function RunnerStatusPanel({ accountId }: { readonly accountId: string }) {
  const query = useOwnRunnerStatusQuery();
  const data = query.data;

  return (
    <Panel title="Poste agent">
      {data === undefined ? (
        <p className="t-secondary" role={query.isError ? "status" : undefined}>
          {query.isError ? "Statut du poste agent indisponible." : "Vérification du poste agent…"}
        </p>
      ) : (
        <div className="u-stack-2">
          <p role="status">{OWN_RUNNER_STATUS_SENTENCES[data.status]}</p>
          {data.status === "ONLINE"
            ? (() => {
                const line = sessionSentence(
                  accountId,
                  data.sessions.find((session) => session.accountId === accountId)?.state,
                );
                return line === null ? null : <p>{line}</p>;
              })()
            : null}
        </div>
      )}
    </Panel>
  );
}
