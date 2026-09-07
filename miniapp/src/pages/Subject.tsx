import { ChevronRight, Lock, Sparkles, SquareCheckBig } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchAccessStatus, fetchLearningState, fetchSubjectDetail, isRealBackedSubject } from "../lib/api";
import { formatMaterialCount } from "../lib/format";
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
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState });

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
  const totalMaterials = subject.sections.reduce((sum, section) => sum + section.itemCount, 0);
  const completedMaterials = learningQuery.data?.completedBySubject[subject.id] ?? 0;
  const readiness = totalMaterials ? Math.min(100, Math.round((completedMaterials / totalMaterials) * 100)) : 0;

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
            <ProgressBar percent={readiness} color={`var(--subject-${subject.accent})`} label="Готовность" />
            <span className={styles.readinessValue}>Изучено: {completedMaterials} из {totalMaterials} · {readiness}%</span>
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
                    <div className={styles.sectionCount}>{formatMaterialCount(section.itemCount)}</div>
                  )}
                </div>
                <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
              </PressableCard>
            ))}
          </div>

          {subject.hasAi && (
            <PressableCard
              className={[styles.sectionRow, styles.aiRow].join(" ")}
              aria-label={`Открыть VMEDA AI по предмету ${subject.title}`}
              onClick={() => {
                hapticSelection();
                navigate(`/ai?subject=${encodeURIComponent(subject.id)}&mode=photo`);
              }}
            >
              <div className={styles.aiContent}>
                <span className={styles.aiIcon} aria-hidden="true">
                  <Icon icon={Sparkles} size={18} />
                </span>
                <div>
                  <div className={styles.aiTitle}>VMEDA AI</div>
                  <div className={styles.aiDescription}>Сфотографируй задание — AI разберёт его по материалам курса</div>
                </div>
              </div>
              <Icon icon={ChevronRight} size={18} color="currentColor" />
            </PressableCard>
          )}

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
