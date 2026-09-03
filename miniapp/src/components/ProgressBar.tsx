import styles from "./ProgressBar.module.css";

interface ProgressBarProps {
  percent: number;
  color?: string;
  label?: string;
}

/** Единственная полоса прогресса на всё приложение — карточка "продолжить", предметная
 * карточка, экран предмета и экран прогресса переиспользуют этот же компонент, а не рисуют
 * свою версию каждый раз (§6 ТЗ: "одна система компонентов"). */
export function ProgressBar({ percent, color, label }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, percent));
  return (
    <div
      className={styles.track}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label}
    >
      <div className={styles.fill} style={{ width: `${clamped}%`, background: color }} />
    </div>
  );
}
