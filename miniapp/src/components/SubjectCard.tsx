import { subjectIcon } from "../lib/subjectIcons";
import { Lock } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { SubjectSummary } from "../lib/types";
import { hapticSelection } from "../lib/telegram";
import { PressableCard } from "./Card";
import { Icon } from "./Icon";
import { ProgressBar } from "./ProgressBar";
import { formatMaterialCount } from "../lib/format";
import styles from "./SubjectCard.module.css";

interface SubjectCardProps {
  subject: SubjectSummary;
  /** Изучено материалов этого предмета; вместе с subject.totalItems даёт реальный прогресс. */
  completed?: number;
}

export function SubjectCard({ subject, completed = 0 }: SubjectCardProps) {
  const navigate = useNavigate();
  const IconComponent = subjectIcon(subject.id);
  const accentVar = `var(--subject-${subject.accent})`;
  const total = subject.totalItems ?? 0;
  const percent = total ? Math.min(100, Math.round((completed / total) * 100)) : (subject.readiness ?? 0);

  function handleOpen() {
    hapticSelection();
    navigate(`/subjects/${subject.id}`);
  }

  return (
    <PressableCard
      className={[styles.card, subject.locked ? styles.locked : ""].join(" ")}
      onClick={handleOpen}
      aria-label={subject.locked ? `${subject.title} — заблокировано` : subject.title}
      style={{ "--subject-accent": accentVar } as React.CSSProperties}
    >
      <span className={styles.accentBar} style={{ background: accentVar }} aria-hidden="true" />
      <div className={styles.top}>
        {/* Флет var(--surface-secondary), не полупрозрачный color-mix() поверх акцента — тот же
            резон совместимости со старым Android WebView, что и у --*-tint токенов в tokens.css. */}
        <span className={styles.iconWrap} style={{ background: "var(--surface-secondary)" }}>
          <Icon icon={subject.locked ? Lock : IconComponent} size={20} color={accentVar} />
        </span>
        {subject.tag && (
          <span className={styles.tag} style={{ background: "var(--surface-secondary)", color: accentVar }}>
            {subject.tag}
          </span>
        )}
      </div>
      <div className={styles.title}>{subject.title}</div>
      {subject.locked ? (
        <div className={styles.lockRow}>
          <Icon icon={Lock} size={12} />
          <span>{subject.lockedReason ?? "Недоступно"}</span>
        </div>
      ) : total && !completed ? (
        <div className={styles.meta}>{formatMaterialCount(total)}</div>
      ) : (
        <div className={styles.readinessRow}>
          <ProgressBar percent={percent} color={accentVar} label={`Изучено: ${subject.title}`} />
          <span className={styles.readinessValue}>{percent}%</span>
        </div>
      )}
    </PressableCard>
  );
}
