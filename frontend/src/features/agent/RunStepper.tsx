import { cx } from "@shared/utils/classNames";
import styles from "./RunStepper.module.css";

export type RunStage = "new-run" | "plan-review" | "execution" | "human-review";

const STAGES: readonly { readonly id: RunStage; readonly label: string }[] = [
  { id: "new-run", label: "Nouveau run" },
  { id: "plan-review", label: "Revue du plan" },
  { id: "execution", label: "Exécution" },
  { id: "human-review", label: "Vérification humaine" },
];

interface RunStepperProps {
  readonly current: RunStage;
}

/**
 * Where the employee is in the run, and what still lies ahead.
 *
 * Stages are named, never given a percentage: the backend reports states, not
 * progress, and inventing a bar would be inventing knowledge.
 */
export function RunStepper({ current }: RunStepperProps) {
  const currentIndex = STAGES.findIndex((stage) => stage.id === current);
  return (
    <ol className={styles.stepper} aria-label="Étapes du run">
      {STAGES.map((stage, index) => (
        <li
          key={stage.id}
          className={cx(
            styles.step,
            index === currentIndex && styles.current,
            index < currentIndex && styles.done,
          )}
          aria-current={stage.id === current ? "step" : undefined}
        >
          {stage.label}
        </li>
      ))}
    </ol>
  );
}
