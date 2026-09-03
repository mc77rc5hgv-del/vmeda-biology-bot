import { Inbox, WifiOff } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Icon } from "./Icon";
import styles from "./StateMessage.module.css";

interface StateMessageProps {
  icon?: LucideIcon;
  title: string;
  body?: string;
  onRetry?: () => void;
}

/** Единый компонент для "нет сети"/"ничего не найдено"/ошибка загрузки (§14, §15 ТЗ:
 * "Обработка ошибок и отсутствие сети" — отдельный обязательный экран MVP, не просто try/catch
 * без UI). */
export function StateMessage({ icon = Inbox, title, body, onRetry }: StateMessageProps) {
  return (
    <div className={styles.wrap} role="status">
      <span className={styles.iconWrap}>
        <Icon icon={icon} size={26} />
      </span>
      <span className={styles.title}>{title}</span>
      {body && <span className={styles.body}>{body}</span>}
      {onRetry && (
        <button type="button" className={styles.retry} onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function OfflineMessage({ onRetry }: { onRetry?: () => void }) {
  return (
    <StateMessage
      icon={WifiOff}
      title="Нет соединения"
      body="Проверь интернет и попробуй ещё раз — материалы появятся, как только связь восстановится."
      onRetry={onRetry}
    />
  );
}
