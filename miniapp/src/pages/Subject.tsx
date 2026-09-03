import { ChevronRight, Lock, SquareCheckBig } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchAccessStatus, fetchSubjectDetail, isRealBackedSubject } from "../lib/api";
import { hapticSelection, useTelegramBackButton } from "../lib/telegram";
import { PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { ProgressBar } from "../components/ProgressBar";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Subject.module.css";

export function SubjectPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate("/"));

  const subjectQuery = useQuery({
    queryKey: ["subject", subjectId],
    queryFn: () => fetchSubjectDetail(subjectId),
  });
  const accessQuery = useQuery({
    queryKey: ["access", subjectId],
    queryFn: () => fetchAccessStatus(subjectId),
  });

  if (subjectQuery.isLoading || accessQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={28} width="60%" />
        <Skeleton height={60} radius="16px" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} height={64} radius="16px" />
        ))}
      </div>
    );
  }

  if (subjectQuery.isError || !subjectQuery.data) {
    return (
      <div className="screen">
        <StateMessage title="Предмет не найден" onRetry={() => subjectQuery.refetch()} />
      </div>
    );
  }

  const subject = subjectQuery.data;
  const locked = accessQuery.isError || !accessQuery.data || !accessQuery.data.canOpenSubject;

  return (
    <div className="screen">
      <div className={styles.header}>
        <h1 className={styles.title}>{subject.title}</h1>
        {locked ? (
          <StateMessage
            icon={Lock}
            title="Раздел пока недоступен"
            body={accessQuery.data?.lockedReason ?? subject.lockedReason ?? "Открой доступ через подписку или рефералов."}
          />
        ) : (
          <div className={styles.readinessRow}>
            <ProgressBar percent={subject.readiness ?? 0} color={`var(--subject-${subject.accent})`} label="Готовность" />
            <span className={styles.readinessValue}>Готовность: {subject.readiness ?? 0}%</span>
          </div>
        )}
      </div>

      {!locked && (
        <>
          <div className={styles.sectionList}>
            {subject.sections.map((section) => (
              <PressableCard
                key={section.id}
                className={styles.sectionRow}
                onClick={() => {
                  hapticSelection();
                  // Реальные предметы: раздел может содержать сотни/тысячи элементов (см.
                  // web_api/content.py) — сначала список (SectionPage), а не сразу материал #1.
                  // Mock-предметы (Этап 2): такого списка нет, старое поведение не трогаем.
                  if (isRealBackedSubject(subject.id)) {
                    navigate(`/subjects/${subject.id}/sections/${section.id}`);
                  } else {
                    navigate(`/materials/${subject.id}/${section.id}/1`);
                  }
                }}
              >
                <div>
                  <div className={styles.sectionTitle}>{section.title}</div>
                  {section.itemCount > 0 && (
                    <div className={styles.sectionCount}>{section.itemCount} элементов</div>
                  )}
                </div>
                <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
              </PressableCard>
            ))}
          </div>

          {!isRealBackedSubject(subject.id) && (
            <PressableCard
              className={styles.sectionRow}
              onClick={() => {
                hapticSelection();
                navigate(`/tests/${subject.id}`);
              }}
            >
              <div>
                <div className={styles.sectionTitle}>Тест по предмету</div>
                <div className={styles.sectionCount}>Проверить себя</div>
              </div>
              <Icon icon={SquareCheckBig} size={18} color="var(--ink-secondary)" />
            </PressableCard>
          )}
        </>
      )}
    </div>
  );
}
