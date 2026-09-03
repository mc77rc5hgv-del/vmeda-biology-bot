import {
  Activity,
  Atom,
  Bone,
  Dna,
  FlaskConical,
  Landmark,
  Lock,
  Microscope,
  Pill,
  Scale,
  Scissors,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { SubjectSummary } from "../lib/types";
import { hapticSelection } from "../lib/telegram";
import { PressableCard } from "./Card";
import { Icon } from "./Icon";
import { ProgressBar } from "./ProgressBar";
import styles from "./SubjectCard.module.css";

/** Предмет → иконка (§9 ТЗ: собственный микродизайн предмета, но единые компоненты и только
 * SVG/CSS — никаких фотореалистичных изображений). */
const SUBJECT_ICONS: Record<string, typeof Activity> = {
  physiology: Activity,
  operative_surgery: Scissors,
  biochemistry: Atom,
  pharmacology: Pill,
  biology: Dna,
  physics: Atom,
  chemistry: FlaskConical,
  anatomy: Bone,
  histology: Microscope,
  latin: Landmark,
  law: Scale,
};

interface SubjectCardProps {
  subject: SubjectSummary;
}

export function SubjectCard({ subject }: SubjectCardProps) {
  const navigate = useNavigate();
  const IconComponent = SUBJECT_ICONS[subject.id] ?? Dna;
  const accentVar = `var(--subject-${subject.accent})`;

  function handleOpen() {
    hapticSelection();
    navigate(`/subjects/${subject.id}`);
  }

  return (
    <PressableCard
      className={[styles.card, subject.locked ? styles.locked : ""].join(" ")}
      onClick={handleOpen}
      aria-label={subject.locked ? `${subject.title} — заблокировано` : subject.title}
    >
      <div className={styles.top}>
        {/* Флет var(--surface-secondary), не полупрозрачный color-mix() поверх акцента — тот же
            резон совместимости со старым Android WebView, что и у --*-tint токенов в tokens.css. */}
        <span className={styles.iconWrap} style={{ background: "var(--surface-secondary)" }}>
          <Icon icon={subject.locked ? Lock : IconComponent} size={20} color={accentVar} />
        </span>
        <span className={styles.tag} style={{ background: "var(--surface-secondary)", color: accentVar }}>
          {subject.tag}
        </span>
      </div>
      <div className={styles.title}>{subject.title}</div>
      {subject.locked ? (
        <div className={styles.lockRow}>
          <Icon icon={Lock} size={12} />
          <span>{subject.lockedReason ?? "Недоступно"}</span>
        </div>
      ) : (
        <div className={styles.readinessRow}>
          <ProgressBar percent={subject.readiness ?? 0} color={accentVar} label={`Готовность: ${subject.title}`} />
          <span className={styles.readinessValue}>{subject.readiness ?? 0}%</span>
        </div>
      )}
    </PressableCard>
  );
}
