import { useState } from "react";
import { ChevronRight, Layers, Lock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchSection } from "../lib/api";
import { hapticSelection, useTelegramBackButton } from "../lib/telegram";
import { PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Section.module.css";

// Backend отдаёт раздел целиком одним ответом (см. web_api/content.py) — у самых больших
// разделов (напр. "Все тесты по биохимии", 1500 уроков) рендерить их все в DOM сразу плохо для
// мобильного скролла (§17 ТЗ: "виртуализация длинных списков"). Пока нет backend-пагинации,
// компенсируем на фронте простым "показать ещё" — честная временная мера, не замена настоящей
// виртуализации/серверной пагинации, которая нужна отдельным шагом.
const PAGE_SIZE = 50;

export function SectionPage() {
  const { subjectId = "", sectionId = "" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(`/subjects/${subjectId}`));
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const sectionQuery = useQuery({
    queryKey: ["section", subjectId, sectionId],
    queryFn: () => fetchSection(subjectId, sectionId),
  });

  if (sectionQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={24} width="60%" />
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} height={48} radius="16px" />
        ))}
      </div>
    );
  }

  if (sectionQuery.isError || !sectionQuery.data) {
    return (
      <div className="screen">
        <StateMessage title="Раздел не найден" onRetry={() => sectionQuery.refetch()} />
      </div>
    );
  }

  const section = sectionQuery.data;

  if (section.kind === "grouped") {
    return (
      <div className="screen">
        <h1 className={styles.header}>Разделы</h1>
        <div className={styles.list} role="list">
          {section.groups.map((group) => (
            <PressableCard
              key={group.id}
              className={[styles.row, group.locked ? styles.rowLocked : ""].join(" ")}
              onClick={() => {
                hapticSelection();
                // Клик по закрытому модулю всё равно ведёт на GroupPage — там 403 от backend
                // рендерится тем же честным locked-состоянием, а не молчаливым "ничего не
                // произошло" (см. Group.tsx). Источник истины о доступе — сервер, не эта пометка.
                navigate(`/subjects/${subjectId}/sections/${sectionId}/groups/${group.id}`);
              }}
            >
              <div>
                <div className={styles.rowTitle}>
                  {group.locked ? "🔒 " : ""}
                  {group.title}
                </div>
                <div className={styles.rowMeta}>
                  {group.locked ? (group.lockedReason ?? "Доступно по подписке") : `${group.itemCount} тем`}
                </div>
              </div>
              <Icon icon={group.locked ? Lock : Layers} size={18} color="var(--ink-secondary)" />
            </PressableCard>
          ))}
        </div>
      </div>
    );
  }

  const visibleItems = section.items.slice(0, visibleCount);

  return (
    <div className="screen">
      <h1 className={styles.header}>Темы</h1>
      <div className={styles.list} role="list">
        {visibleItems.map((item) => (
          <PressableCard
            key={item.id}
            className={styles.row}
            onClick={() => {
              hapticSelection();
              navigate(`/materials/${subjectId}/${sectionId}/${item.id}`);
            }}
          >
            <div>
              <div className={styles.rowTitle}>{item.title}</div>
              <div className={styles.rowMeta}>
                {item.order} из {item.total}
              </div>
            </div>
            <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
          </PressableCard>
        ))}
      </div>
      {visibleCount < section.items.length && (
        <PressableCard className={styles.row} onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
          <span className={styles.rowTitle}>
            Показать ещё ({section.items.length - visibleCount})
          </span>
        </PressableCard>
      )}
    </div>
  );
}
