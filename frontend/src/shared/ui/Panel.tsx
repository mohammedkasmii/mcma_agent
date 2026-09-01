import type { ReactNode } from "react";
import { cx } from "@shared/utils/classNames";
import styles from "./Panel.module.css";

interface PanelProps {
  readonly title: string;
  /** Short sentence under the title. Optional. */
  readonly description?: string;
  /** Status chip or action rendered on the title row. */
  readonly aside?: ReactNode;
  readonly children?: ReactNode;
}

/**
 * The one working surface of the application. Panels carry a hairline and
 * a title row; they are not decorative cards and do not nest.
 */
export function Panel({ title, description, aside, children }: PanelProps) {
  return (
    <section className={styles.panel}>
      <header className={styles.header}>
        <div>
          <h2 className="t-section-title">{title}</h2>
          {description ? <p className={cx("t-secondary", styles.description)}>{description}</p> : null}
        </div>
        {aside ? <div className={styles.aside}>{aside}</div> : null}
      </header>
      {children ? <div className={styles.body}>{children}</div> : null}
    </section>
  );
}
