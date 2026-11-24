import styles from "./PageHeader.module.css";

interface PageHeaderProps {
  title: string;
  /** Где находится экран — обычно название предмета. */
  eyebrow?: string;
  meta?: string;
}

/** Шапка списочных экранов: откуда ты пришёл, где ты сейчас и сколько здесь всего. */
export function PageHeader({ title, eyebrow, meta }: PageHeaderProps) {
  return (
    <header className={styles.head}>
      {eyebrow && <span className={styles.eyebrow}>{eyebrow}</span>}
      <h1 className={styles.title}>{title}</h1>
      {meta && <span className={styles.meta}>{meta}</span>}
    </header>
  );
}
