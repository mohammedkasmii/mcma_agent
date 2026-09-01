import type { ButtonHTMLAttributes } from "react";
import { cx } from "@shared/utils/classNames";
import styles from "./Button.module.css";

type ButtonVariant = "primary" | "secondary";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  readonly variant?: ButtonVariant;
}

/**
 * The one button treatment: square, near-black for the primary action,
 * outlined for everything else, per the approved visual reference.
 *
 * `type` defaults to "button". A button that submits by accident is how a
 * form-shaped screen performs an action nobody asked for.
 */
export function Button({ variant = "secondary", className, type, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      type={type ?? "button"}
      className={cx(styles.button, styles[variant], className)}
    />
  );
}
