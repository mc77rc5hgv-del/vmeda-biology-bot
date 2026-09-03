import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import styles from "./Card.module.css";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  flat?: boolean;
}

/** Базовая поверхность (белая/тёмная карточка с тенью) — единственное место, где задаётся
 * радиус/тень/отступ карточки во всём приложении (см. §6 ТЗ: "единая сетка, одна система компонентов"). */
export function Card({ children, flat, className, ...rest }: CardProps) {
  const cls = [styles.card, flat ? styles.flat : "", className].filter(Boolean).join(" ");
  return (
    <div className={cls} {...rest}>
      {children}
    </div>
  );
}

interface PressableCardProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  flat?: boolean;
}

/** То же самое, но как <button> — для карточек-ссылок (продолжить обучение, предмет, ...).
 * Гарантирует область нажатия и клавиатурную доступность без отдельного onClick-дива. */
export function PressableCard({ children, flat, className, ...rest }: PressableCardProps) {
  const cls = [styles.card, styles.pressable, flat ? styles.flat : "", className].filter(Boolean).join(" ");
  return (
    <button className={cls} type="button" {...rest}>
      {children}
    </button>
  );
}
