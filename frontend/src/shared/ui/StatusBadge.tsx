import type { ReactNode } from "react";
import { cx } from "@shared/utils/classNames";
import styles from "./StatusBadge.module.css";

export type StatusTone =
  | "connected"
  | "reconnect"
  | "readonly"
  | "running"
  | "review"
  | "failed"
  | "completed"
  | "idle";

interface StatusBadgeProps {
  readonly tone: StatusTone;
  readonly children: ReactNode;
}

/**
 * A status is always readable as words. The tone adds colour and a border
 * treatment on top of the label; it never replaces it, so the badge stays
 * legible without colour perception.
 */
export function StatusBadge({ tone, children }: StatusBadgeProps) {
  return <span className={cx(styles.badge, styles[tone])}>{children}</span>;
}
