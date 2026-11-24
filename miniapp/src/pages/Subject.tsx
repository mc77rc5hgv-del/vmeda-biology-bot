import { subscriptionPath } from "../lib/subscriptions";
import { useEffect, useRef } from "react";
import { BookOpenCheck, ChevronRight, Layers, ListChecks, Lock, Microscope, Sparkles, SquareCheckBig } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, useLocation, useNavigate, useParams } from "react-router-dom";
import { enterSubject, hasContentSession, fetchAccessStatus, fetchLearningState, fetchSubjectDetail, isRealBackedSubject } from "../lib/api";
import { formatMaterialCount } from "../lib/format";
import { subjectIcon } from "../lib/subjectIcons";
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
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  const visited = useRef("");
  const entryMutation = useMutation({mutationFn: () => enterSubject(subjectId), onSuccess: (data) => {
    queryClient.setQueryData(["access", subjectId], data);
    void queryClient.invalidateQueries({queryKey: ["subscription"]});
  }});
  useEffect(() => {
    if (hasContentSession() && ["biology", "physics", "chemistry"].includes(subjectId) && visited.current !== subjectId) {
      visited.current = subjectId;
      entryMutation.mutate();
    }
  }, [subjectId, entryMutation]);
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

  if (subjectQuery.isLoading || accessQuery.isLoading || entryMutation.isPending) {
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
  if (accessQuery.isError || !accessQuery.data) {
    return <div className="screen"><StateMessage title="Не удалось проверить доступ" body="Повтори проверку. Твоя подписка не изменена." onRetry={() => accessQuery.refetch()} /></div>;
  }
  if (accessQuery.data.subscriptionRequired) {
    return <Navigate to={subscriptionPath(subjectId, pathname)} replace />;
  }
  const locked = !accessQuery.data.canOpenSubject;
  const totalMaterials = subject.sections.reduce((sum, section) => sum + section.itemCount, 0);
  const completedMaterials = learningQuery.data?.completedBySubject[subject.id] ?? 0;
  const readiness = totalMaterials ? Math.min(100, Math.round((completedMaterials / totalMaterials) * 100)) : 0;

  return (
    <div className="screen">
      <div className={styles.header}>
        {entryMutation.isError && <StateMessage title="Не удалось открыть доступ" onRetry={() => entryMutation.mutate()} />}
        {accessQuery.data.trialAvailable && <button type="button" className={styles.trialButton} disabled={entryMutation.isPending} onClick={() => entryMutation.mutate()}>{entryMutation.isPending ? "Открываем…" : "Открыть пробный доступ к гистологии"}</button>}
        <div className={styles.titleRow}>
          <span className={styles.subjectIcon} aria-hidden="true"><Icon icon={subjectIcon(subject.id)} size={24} /></span>
          <div className={styles.titleCopy}>
            <h1 className={styles.title}>{subject.title}</h1>
            {!locked && totalMaterials > 0 && <span className={styles.subtitle}>{formatMaterialCount(totalMaterials)}</span>}
          </div>
        </div>
        {locked ? (
          <StateMessage
            icon={Lock}
            title="Раздел пока недоступен"
            body={accessQuery.data?.lockedReason ?? subject.lockedReason ?? "Открой доступ через подписку или рефералов."}
          />
        ) : (
          <div className={styles.readinessRow}>
            <ProgressBar percent={readiness} color={`var(--subject-${subject.accent}-fg)`} label="Готовность" />
            <span className={styles.readinessValue}>Изучено {completedMaterials} · {readiness}%</span>
          </div>
        )}
      </div>

      {subject.id === "anatomy" && (
        <PressableCard
          className={[styles.sectionRow, styles.anatomyExamRow].join(" ")}
          aria-label="Открыть экзаменационные тесты по анатомии"
          onClick={() => {
            hapticSelection();
            navigate("/tests/anatomy");
          }}
        >
          <span className={styles.anatomyExamIcon} aria-hidden="true">
            <Icon icon={BookOpenCheck} size={20} />
          </span>
          <div className={styles.anatomyExamContent}>
            <div className={styles.anatomyExamTitle}>Экзаменационный тест</div>
            <div className={styles.anatomyExamDescription}>1 040 вопросов · пояснения · работа над ошибками</div>
          </div>
          <Icon icon={ChevronRight} size={18} color="currentColor" />
        </PressableCard>
      )}

      {subject.id === "histology" && !locked && (
        <div className={styles.sectionList}>
          {[
            { title: "Экзамен", path: "/histology/exam", icon: BookOpenCheck },
            { title: "ДИАГНОСТИКИ", path: "/histology/diagnostics", icon: Microscope },
          ].map(({ title, path, icon }) => (
            <PressableCard
              key={path}
              className={[styles.sectionRow, styles.histologyExamRow].join(" ")}
              onClick={() => { hapticSelection(); navigate(path); }}
            >
              <span className={styles.histologyExamIcon} aria-hidden="true">
                <Icon icon={icon} size={21} />
              </span>
              <div className={styles.anatomyExamContent}>
                <div className={styles.anatomyExamTitle}>{title}</div>
              </div>
              <Icon icon={ChevronRight} size={18} color="currentColor" />
            </PressableCard>
          ))}
        </div>
      )}

      {!locked && (
        <>
          <h2 className={styles.sectionsHeading}>Разделы</h2>
          <div className={styles.sectionList}>
            {subject.sections.filter((section) => !(subject.id === "histology" && section.id === "specimens")).map((section) => (
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
                <span className={styles.sectionIcon} aria-hidden="true">
                  <Icon icon={section.kind === "grouped" ? Layers : ListChecks} size={20} />
                </span>
                <div className={styles.sectionCopy}>
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
