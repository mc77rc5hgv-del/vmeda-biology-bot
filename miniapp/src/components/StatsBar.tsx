import { useState } from "react";
import { Flame, Target, Zap } from "lucide-react";
import type { DashboardStats } from "../lib/types";
import { Icon } from "./Icon";
import styles from "./StatsBar.module.css";

interface StatsBarProps {
  stats: DashboardStats;
}

type StatKey = "streak" | "xp" | "readiness";

const EXPLANATIONS: Record<StatKey, string> = {
  streak: "Серия — количество дней подряд, когда ты открывал и проходил хотя бы один материал или тест.",
  xp: "XP — баллы за завершённые активности: пройденную тему, тест, повторение ошибок.",
  readiness: "Готовность — общий показатель по всем предметам: 30% завершённые темы, 30% результаты тестов, 20% повторение ошибок, 20% экзаменационные тренировки.",
};

/** Компактная строка учебной статистики (§8 ТЗ) — это не декоративные цифры: тап по любой
 * плашке раскрывает объяснение, как именно посчитано число, ровно по требованию "пользователь
 * должен понимать, как рассчитываются показатели". */
export function StatsBar({ stats }: StatsBarProps) {
  const [active, setActive] = useState<StatKey | null>(null);

  const items: Array<{ key: StatKey; icon: typeof Flame; value: string; label: string; accent: string }> = [
    { key: "streak", icon: Flame, value: `${stats.streakDays} дн.`, label: "Серия", accent: "var(--amber-tint)" },
    { key: "xp", icon: Zap, value: `${stats.xp}`, label: "XP", accent: "var(--academic-blue-tint)" },
    { key: "readiness", icon: Target, value: `${stats.readinessPercent}%`, label: "Готовность", accent: "var(--muted-teal-tint)" },
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
