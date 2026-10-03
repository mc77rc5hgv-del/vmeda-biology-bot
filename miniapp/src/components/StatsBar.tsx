import { useState } from "react";
import { Bookmark, CircleCheckBig, Target } from "lucide-react";
import { Icon } from "./Icon";
import styles from "./StatsBar.module.css";

interface StatsBarProps {
  completed: number;
  accuracy: number;
  favorites: number;
}

type StatKey = "completed" | "accuracy" | "favorites";

const EXPLANATIONS: Record<StatKey, string> = {
  completed: "Количество материалов, которые ты отметил изученными.",
  accuracy: "Доля правильных ответов во всех пройденных тестовых заданиях.",
  favorites: "Материалы, сохранённые для быстрого возвращения и повторения.",
};

/** Компактная строка реальной учебной статистики: тап по любой плашке объясняет показатель. */
export function StatsBar({ completed, accuracy, favorites }: StatsBarProps) {
  const [active, setActive] = useState<StatKey | null>(null);

  const items: Array<{ key: StatKey; icon: typeof Target; value: string; label: string; accent: string }> = [
    { key: "completed", icon: CircleCheckBig, value: `${completed}`, label: "Изучено", accent: "var(--success-tint)" },
    { key: "accuracy", icon: Target, value: `${accuracy}%`, label: "Точность", accent: "var(--academic-blue-tint)" },
    { key: "favorites", icon: Bookmark, value: `${favorites}`, label: "Сохранено", accent: "var(--amber-tint)" },
  ];

  return (
    <div>
      <div className={styles.bar} role="list">
        {items.map((item) => (
          <button
            key={item.key}
            type="button"
            className={styles.pill}
            role="listitem"
            aria-expanded={active === item.key}
            onClick={() => setActive((prev) => (prev === item.key ? null : item.key))}
          >
            <span className={styles.iconWrap} style={{ background: item.accent }}>
              <Icon icon={item.icon} size={16} />
            </span>
            <span>
              <span className={styles.value}>{item.value}</span>
              <br />
              <span className={styles.label}>{item.label}</span>
            </span>
          </button>
        ))}
      </div>
      {active && (
        <p style={{ fontSize: 12, color: "var(--ink-secondary)", marginTop: "var(--space-2)", lineHeight: 1.4 }}>
          {EXPLANATIONS[active]}
        </p>
      )}
    </div>
  );
}
