import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { ContinueItem } from "../lib/types";
import { hapticSelection } from "../lib/telegram";
import { Card } from "./Card";
import { Icon } from "./Icon";
import { ProgressBar } from "./ProgressBar";
import styles from "./ContinueCard.module.css";

interface ContinueCardProps {
  item: ContinueItem;
}

/** Главная карточка "Продолжить обучение" (§8 ТЗ) — открывает последнюю незавершённую
 * активность, а не общий экран предмета: тап сразу ведёт на конкретный материал. */
export function ContinueCard({ item }: ContinueCardProps) {
  const navigate = useNavigate();
  const percent = Math.round((item.order / item.totalInSection) * 100);

  function handleContinue() {
    hapticSelection();
    navigate(`/subjects/${item.subjectId}`);
  }

  return (
    <Card className={styles.card}>
      <span className={styles.eyebrow}>Следующий шаг</span>
      <div>
        <div className={styles.title}>
          {item.subjectTitle} · {item.sectionTitle}
        </div>
        <div className={styles.meta}>
          Тема {item.order} из {item.totalInSection}
        </div>
      </div>
      <div className={styles.footer}>
        <div className={styles.progressWrap}>
          <ProgressBar percent={percent} color="#fff" label="Прогресс раздела" />
        </div>
        <button type="button" className={styles.cta} onClick={handleContinue}>
          Продолжить
          <Icon icon={ChevronRight} size={16} />
        </button>
      </div>
    </Card>
  );
}
