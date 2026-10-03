import styles from "./Skeleton.module.css";

interface SkeletonProps {
  height?: number;
  width?: string;
  radius?: string;
}

/** Пустой экран — плохой UX даже на 250 мс мок-задержке (§17 ТЗ: "skeleton вместо пустого
 * экрана"). Используется на каждой странице вместо условного "Загрузка..." текста. */
export function Skeleton({ height = 16, width = "100%", radius }: SkeletonProps) {
  return (
    <div
      className={styles.block}
      style={{ height, width, borderRadius: radius }}
      aria-hidden="true"
    />
  );
}
