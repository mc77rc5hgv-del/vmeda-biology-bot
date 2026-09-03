import { useState } from "react";
import { ChevronRight, Lock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchGroup } from "../lib/api";
import { ApiError } from "../lib/apiClient";
import { hapticSelection, useTelegramBackButton } from "../lib/telegram";
import { PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Section.module.css";

const PAGE_SIZE = 50; // см. Section.tsx за тем, почему это временная мера, а не виртуализация

export function GroupPage() {
  const { subjectId = "", sectionId = "", groupId = "" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(`/subjects/${subjectId}/sections/${sectionId}`));
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);

  const groupQuery = useQuery({
    queryKey: ["group", subjectId, sectionId, groupId],
    queryFn: () => fetchGroup(subjectId, sectionId, groupId),
  });

  if (groupQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={24} width="60%" />
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} height={48} radius="16px" />
        ))}
      </div>
    );
  }

  if (groupQuery.isError || !groupQuery.data) {
    const err = groupQuery.error;
    if (err instanceof ApiError && err.status === 403) {
      // Модуль показан в списке (Section.tsx) с пометкой locked ДО этого перехода — сервер
      // остаётся единственным источником истины: прямой переход по ссылке на закрытый модуль
      // должен показать ровно тот же locked-текст, что и клик по помеченной карточке.
      return (
        <div className="screen">
          <StateMessage icon={Lock} title="Раздел закрыт" body={err.message} />
        </div>
      );
    }
    return (
      <div className="screen">
        <StateMessage title="Группа не найдена" onRetry={() => groupQuery.refetch()} />
      </div>
    );
  }

  const group = groupQuery.data;
  const visibleItems = group.items.slice(0, visibleCount);

  return (
    <div className="screen">
      <h1 className={styles.header}>{group.title}</h1>
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
      {visibleCount < group.items.length && (
        <PressableCard className={styles.row} onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
          <span className={styles.rowTitle}>Показать ещё ({group.items.length - visibleCount})</span>
        </PressableCard>
      )}
    </div>
  );
}
