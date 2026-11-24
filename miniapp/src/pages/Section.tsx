import { subscriptionPath } from "../lib/subscriptions";
import { useCallback, useState } from "react";
import { ChevronRight, Layers, Lock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchLearningState, fetchSection, fetchSubjectDetail, hasContentSession } from "../lib/api";
import { ApiError } from "../lib/apiClient";
import { formatMaterialCount } from "../lib/format";
import { hapticSelection, useTelegramBackButton } from "../lib/telegram";
import { PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { TelegramContentGate } from "../components/TelegramContentGate";
import { LoadMore } from "../components/LoadMore";
import { MaterialRow } from "../components/MaterialRow";
import { PageHeader } from "../components/PageHeader";
import styles from "./Section.module.css";

// Раздел приходит целиком одним ответом: это только заголовки (самый большой раздел — 540,
// десятки килобайт), так что серверная пагинация не нужна. В DOM же рисуем порциями и
// догружаем их сами при прокрутке (LoadMore), чтобы длинный список не тормозил на слабых телефонах.
const PAGE_SIZE = 50;

export function SectionPage() {
  const { subjectId = "", sectionId = "" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(`/subjects/${subjectId}`));
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const showMore = useCallback(() => setVisibleCount((count) => count + PAGE_SIZE), []);
  const hasSession = hasContentSession();

  const sectionQuery = useQuery({
    queryKey: ["section", subjectId, sectionId],
    queryFn: () => fetchSection(subjectId, sectionId),
    enabled: hasSession,
  });
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState, enabled: hasSession });
  // Тот же ключ, что у экрана предмета: название раздела обычно уже лежит в кэше.
  const subjectQuery = useQuery({ queryKey: ["subject", subjectId], queryFn: () => fetchSubjectDetail(subjectId), enabled: hasSession });
  const sectionRef = subjectQuery.data?.sections.find((item) => item.id === sectionId);

  if (!hasSession) {
    return (
      <div className="screen">
        <TelegramContentGate />
      </div>
    );
  }

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
    if (sectionQuery.error instanceof ApiError && sectionQuery.error.status === 503) {
      return <div className="screen"><StateMessage title="Раздел временно недоступен" body={sectionQuery.error.message} onRetry={() => sectionQuery.refetch()} /></div>;
    }
    const error = sectionQuery.error;
    if (error instanceof ApiError && error.status === 403) {
      return <div className="screen"><StateMessage icon={Lock} title="Раздел закрыт" body={error.message} onRetry={() => navigate(subscriptionPath(subjectId, `/subjects/${subjectId}/sections/${sectionId}`))} actionLabel="Открыть подписки" /></div>;
    }
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
        <PageHeader
          eyebrow={subjectQuery.data?.title}
          title={sectionRef?.title ?? "Разделы"}
          meta={sectionRef?.itemCount ? formatMaterialCount(sectionRef.itemCount) : undefined}
        />
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
              <span className={styles.rowIcon} aria-hidden="true">
                <Icon icon={group.locked ? Lock : Layers} size={18} />
              </span>
              <div className={styles.rowCopy}>
                <div className={styles.rowTitle}>{group.title}</div>
                <div className={styles.rowMeta}>
                  {group.locked ? (group.lockedReason ?? "Доступно по подписке") : formatMaterialCount(group.itemCount)}
                </div>
              </div>
              <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
            </PressableCard>
          ))}
        </div>
      </div>
    );
  }

  const visibleItems = section.items.slice(0, visibleCount);
  const completedKeys = new Set(learningQuery.data?.completedKeys ?? []);
  const completedHere = section.items.filter((item) => completedKeys.has(`${subjectId}/${sectionId}/${item.id}`)).length;

  return (
    <div className="screen">
      <PageHeader
        eyebrow={subjectQuery.data?.title}
        title={sectionRef?.title ?? "Темы"}
        meta={`${formatMaterialCount(section.items.length)}${completedHere ? ` · изучено ${completedHere}` : ""}`}
      />
      <div className={styles.list} role="list">
        {visibleItems.map((item) => (
          <MaterialRow
            key={item.id}
            order={item.order}
            title={item.title}
            done={completedKeys.has(`${subjectId}/${sectionId}/${item.id}`)}
            onOpen={() => navigate(`/materials/${subjectId}/${sectionId}/${item.id}`)}
          />
        ))}
      </div>
      {visibleCount < section.items.length && (
        <LoadMore
          remaining={section.items.length - visibleCount}
          onMore={showMore}
          className={styles.row}
          titleClassName={styles.rowTitle}
        />
      )}
    </div>
  );
}
