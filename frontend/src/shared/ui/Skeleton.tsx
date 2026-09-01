import { cx } from "@shared/utils/classNames";
import styles from "./Skeleton.module.css";

interface SkeletonProps {
  /** Width as a CSS length token name is avoided; use a coarse size step. */
  readonly size?: "sm" | "md" | "lg";
}

/**
 * A structural placeholder for content that has not arrived. It carries no
 * text, so nothing invented can ever be mistaken for real portal data.
 * Screen readers skip it: the surrounding region announces the loading
 * state once instead.
 */
export function Skeleton({ size = "md" }: SkeletonProps) {
  return <span aria-hidden="true" className={cx(styles.bar, styles[size])} />;
}
