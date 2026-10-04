import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { ContinueItem } from "../lib/types";
import { hapticSelection } from "../lib/telegram";
import { Card } from "./Card";
import { Icon } from "./Icon";
import { ProgressBar } from "./ProgressBar";
import styles from "./ContinueCard.module.css";
import { SubjectTheme } from "./SubjectTheme";

interface ContinueCardProps {
  item: ContinueItem;
}

/** Главная карточка "Продолжить обучение" (§8 ТЗ) — открывает последнюю незавершённую
 * активность, а не общий экран предмета: тап сразу ведёт на конкретный материал. */
export function ContinueCard({ item }: ContinueCardProps) {
  const navigate = useNavigate();
  const percent = item.totalInSection > 0 ? Math.round((item.order / item.totalInSection) * 100) : 0;

  function handleContinue() {
    hapticSelection();
    if (item.path) {
      navigate(item.path);
    } else if (item.sectionId && item.materialId) {
      navigate(`/materials/${item.subjectId}/${item.sectionId}/${item.materialId}`);
    } else {
      navigate(`/subjects/${item.subjectId}`);
    }
  }

  return (
    <SubjectTheme subjectId={item.subjectId}>
    <Card className={styles.card}>
      <span className={styles.eyebrow}>Следующий шаг</span>
      <div>
        <div className={styles.title}>
          {item.subjectTitle} · {item.sectionTitle}
        </div>
        <div className={styles.meta}>
          {item.totalInSection > 0 ? `Тема ${item.order} из ${item.totalInSection}` : "Вернуться к последнему занятию"}
        </div>
      </div>
      <div className={styles.footer}>
        <div className={styles.progressWrap}>
          {item.totalInSection > 0 && <ProgressBar percent={percent} color="#fff" label="Прогресс раздела" />}
        </div>
        <button type="button" className={styles.cta} onClick={handleContinue}>
          Продолжить
          <Icon icon={ChevronRight} size={16} />
        </button>
      </div>
    </Card>
    </SubjectTheme>
  );
}
