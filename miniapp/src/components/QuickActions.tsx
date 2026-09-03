import { Camera, RotateCcw, SquareCheckBig } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { hapticSelection } from "../lib/telegram";
import { PressableCard } from "./Card";
import { Icon } from "./Icon";
import styles from "./QuickActions.module.css";

/** Три быстрых действия главного экрана (§8 ТЗ):
 * — «Тест» открывает рекомендованную тренировку;
 * — «Повторить» открывает темы, требующие повторения;
 * — «Фото в AI» запускает отправку фотографии задания.
 * На Этапе 2 (тестовые данные) ведут на заглушечные/ближайшие осмысленные экраны —
 * реальный подбор "рекомендованного теста"/"тем на повтор" появится вместе с API. */
export function QuickActions() {
  const navigate = useNavigate();

  const actions = [
    {
      key: "test",
      icon: SquareCheckBig,
      label: "Тест",
      accent: "var(--academic-blue-tint)",
      onClick: () => navigate("/tests/biochemistry"),
    },
    {
      key: "repeat",
      icon: RotateCcw,
      label: "Повторить",
      accent: "var(--amber-tint)",
      onClick: () => navigate("/progress"),
    },
    {
      key: "ai-photo",
      icon: Camera,
      label: "Фото в AI",
      accent: "var(--academy-red-tint)",
      onClick: () => navigate("/ai?mode=photo"),
    },
  ];

  return (
    <div className={styles.row} role="list">
      {actions.map((action) => (
        <PressableCard
          key={action.key}
          className={styles.action}
          role="listitem"
          onClick={() => {
            hapticSelection();
            action.onClick();
          }}
        >
          <span className={styles.iconWrap} style={{ background: action.accent }}>
            <Icon icon={action.icon} size={20} />
          </span>
          <span className={styles.label}>{action.label}</span>
        </PressableCard>
      ))}
    </div>
  );
}
