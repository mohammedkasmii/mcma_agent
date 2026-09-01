import type { ReactNode } from "react";
import styles from "./EmptyState.module.css";

interface EmptyStateProps {
  readonly title: string;
  readonly children?: ReactNode;
}

/**
 * An empty surface says what is missing and what happens next. It never
 * apologises and never shows a placeholder record that could be read as
 * real claim data.
 */
export function EmptyState({ title, children }: EmptyStateProps) {
  return (
    <div className={styles.root}>
      <p className={styles.title}>{title}</p>
      {children ? <p className="t-secondary">{children}</p> : null}
    </div>
  );
}
