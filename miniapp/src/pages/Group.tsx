import { subscriptionPath } from "../lib/subscriptions";
import { Fragment, useCallback, useState } from "react";
import { ChevronRight, Layers, Lock } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchGroup, fetchLearningState, fetchSubjectDetail, hasContentSession } from "../lib/api";
import { formatMaterialCount } from "../lib/format";
import { ApiError } from "../lib/apiClient";
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

const PAGE_SIZE = 50; // порционная отрисовка с автодогрузкой, см. Section.tsx

export function GroupPage() {
  const { subjectId = "", sectionId = "", groupId = "" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(groupQuery.data?.parentId
    ? `/subjects/${subjectId}/sections/${sectionId}/groups/${groupQuery.data.parentId}`
    : `/subjects/${subjectId}/sections/${sectionId}`));
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const showMore = useCallback(() => setVisibleCount((count) => count + PAGE_SIZE), []);
  const hasSession = hasContentSession();

  const groupQuery = useQuery({
    queryKey: ["group", subjectId, sectionId, groupId],
    queryFn: () => fetchGroup(subjectId, sectionId, groupId),
    enabled: hasSession,
  });
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState, enabled: hasSession });
  const subjectQuery = useQuery({ queryKey: ["subject", subjectId], queryFn: () => fetchSubjectDetail(subjectId), enabled: hasSession });
  const sectionTitle = subjectQuery.data?.sections.find((item) => item.id === sectionId)?.title;

  if (!hasSession) {
    return (
      <div className="screen">
        <TelegramContentGate />
      </div>
    );
  }

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
          <StateMessage icon={Lock} title="Раздел закрыт" body={err.message} onRetry={() => navigate(subscriptionPath(subjectId, `/subjects/${subjectId}/sections/${sectionId}/groups/${groupId}`))} actionLabel="Выбрать подписку" />
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
  const headings = new Map(group.sections?.filter((section) => section.items.length).map((section) => [section.items[0].id, section.title]));

  return (
    <div className="screen">
      <PageHeader
        eyebrow={[subjectQuery.data?.title, sectionTitle].filter(Boolean).join(" · ") || undefined}
        title={group.title}
        meta={group.items.length ? formatMaterialCount(group.items.length) : undefined}
      />
      {group.subgroups?.map((subgroup) => (
        <PressableCard key={subgroup.id} className={styles.row} onClick={() => {
          hapticSelection();
          navigate(`/subjects/${subjectId}/sections/${sectionId}/groups/${subgroup.id}`);
        }}>
          <span className={styles.rowIcon} aria-hidden="true"><Icon icon={Layers} size={18} /></span>
          <div className={styles.rowCopy}><div className={styles.rowTitle}>{subgroup.title}</div><div className={styles.rowMeta}>{formatMaterialCount(subgroup.item_count)}</div></div>
          <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
        </PressableCard>
      ))}
      <div className={styles.list} role="list">
        {visibleItems.map((item) => {
          const done = learningQuery.data?.completedKeys.includes(`${subjectId}/${sectionId}/${item.id}`) ?? false;
          return (
          <Fragment key={item.id}>
          {headings.has(item.id) && <h2 className={styles.sectionHeading}>{headings.get(item.id)}</h2>}
          <MaterialRow
            order={item.order}
            title={item.title}
            done={done}
            onOpen={() => navigate(`/materials/${subjectId}/${sectionId}/${item.id}`)}
          />
          </Fragment>
          );
        })}
      </div>
      {visibleCount < group.items.length && (
        <LoadMore
          remaining={group.items.length - visibleCount}
          onMore={showMore}
          className={styles.row}
          titleClassName={styles.rowTitle}
        />
      )}
    </div>
  );
}
