import { Check, ChevronRight } from "lucide-react";
import { hapticSelection } from "../lib/telegram";
import { PressableCard } from "./Card";
import { Icon } from "./Icon";
import styles from "./MaterialRow.module.css";

interface MaterialRowProps {
  order: number | string;
  title: string;
  done: boolean;
  onOpen: () => void;
}

/** Строка материала в списке раздела/группы: номер слева, отметка «изучено» вместо номера. */
export function MaterialRow({ order, title, done, onOpen }: MaterialRowProps) {
  return (
    <PressableCard
      className={styles.row}
      role="listitem"
      aria-label={done ? `${title} — изучено` : title}
      onClick={() => {
        hapticSelection();
        onOpen();
      }}
    >
      <span className={[styles.badge, done ? styles.done : ""].join(" ")} aria-hidden="true">
        {done ? <Icon icon={Check} size={16} /> : order}
      </span>
      <span className={styles.title}>{title}</span>
      <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
    </PressableCard>
  );
}
