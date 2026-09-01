import type { ReactNode } from "react";
import styles from "./Section.module.css";

interface SectionProps {
  /** Short eyebrow label, rendered in the design's monospaced small caps. */
  readonly label: string;
  /** Optional right-aligned count or note. Must be real, never invented. */
  readonly aside?: string | undefined;
  readonly children: ReactNode;
}

/**
 * A labelled block inside a panel, matching the approved reference: a
 * monospaced eyebrow, an optional factual aside, then the content.
 */
export function Section({ label, aside, children }: SectionProps) {
  return (
    <section className={styles.section}>
      <div className={styles.head}>
        <span className="t-eyebrow">{label}</span>
        {aside === undefined ? null : <span className={styles.aside}>{aside}</span>}
      </div>
      {children}
    </section>
  );
}
