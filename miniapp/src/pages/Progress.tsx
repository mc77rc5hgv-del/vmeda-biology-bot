import { useQuery } from "@tanstack/react-query";
import { Bookmark, ChevronRight, CircleCheckBig, Target } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { fetchLearningState, fetchSubjectDetail, fetchSubjects } from "../lib/api";
import { useTelegramBackButton } from "../lib/telegram";
import { Card, PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { ProgressBar } from "../components/ProgressBar";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Progress.module.css";

export function ProgressPage() {
  useTelegramBackButton(null);
  const navigate = useNavigate();
  const subjectsQuery = useQuery({ queryKey: ["subjects"], queryFn: fetchSubjects });
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState });
  const detailsQuery = useQuery({
    queryKey: ["subject-totals", ...(subjectsQuery.data?.map((item) => item.id) ?? [])],
    enabled: Boolean(subjectsQuery.data),
    queryFn: async () => Promise.all((subjectsQuery.data ?? []).map((item) => fetchSubjectDetail(item.id))),
    staleTime: 5 * 60_000,
  });

  if (subjectsQuery.isLoading || learningQuery.isLoading || detailsQuery.isLoading) {
    return <div className="screen"><Skeleton height={30} width="50%" />{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={72} radius="16px" />)}</div>;
  }
  if (subjectsQuery.isError || learningQuery.isError || !subjectsQuery.data || !learningQuery.data) {
    return <div className="screen"><StateMessage title="Не удалось загрузить прогресс" onRetry={() => { subjectsQuery.refetch(); learningQuery.refetch(); }} /></div>;
  }

  const totals = new Map((detailsQuery.data ?? []).filter(Boolean).map((subject) => [
    subject!.id,
    subject!.sections.reduce((sum, section) => sum + section.itemCount, 0),
  ]));
  const learning = learningQuery.data;
  const accuracy = learning.quizAttempts ? Math.round((learning.quizCorrect / learning.quizAttempts) * 100) : 0;

  return (
    <div className="screen">
      <div className="page-intro">
        <h1 style={{ fontSize: 24, fontWeight: 760 }}>Моё обучение</h1>
        <p style={{ marginTop: 5, color: "var(--ink-secondary)", fontSize: 14 }}>Реальные результаты сохраняются между занятиями</p>
      </div>

      <div className={styles.statsGrid}>
        <Card className={styles.statCard}>
          <Icon icon={CircleCheckBig} size={21} color="var(--success)" />
          <strong className={styles.statValue}>{learning.completedTotal}</strong>
          <span className={styles.statLabel}>тем изучено</span>
        </Card>
        <Card className={styles.statCard}>
          <Icon icon={Target} size={21} color="var(--academic-blue)" />
          <strong className={styles.statValue}>{accuracy}%</strong>
          <span className={styles.statLabel}>точность ответов</span>
        </Card>
      </div>

      <section aria-labelledby="subjects-progress">
        <h2 id="subjects-progress" className={styles.sectionTitle}>По предметам</h2>
        <div className={styles.list}>
          {subjectsQuery.data.map((subject) => {
            const completed = learning.completedBySubject[subject.id] ?? 0;
            const total = totals.get(subject.id) ?? 0;
            const percent = total ? Math.min(100, Math.round((completed / total) * 100)) : 0;
            return (
              <PressableCard key={subject.id} onClick={() => navigate(`/subjects/${subject.id}`)} className={styles.subjectCard}>
                <div className={styles.subjectTop}>
                  <strong className={styles.subjectName}>{subject.title}</strong>
                  <span className={styles.subjectMeta}>{completed} из {total}</span>
                </div>
                <ProgressBar percent={percent} color={`var(--subject-${subject.accent})`} label={`Прогресс: ${percent}%`} />
              </PressableCard>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="favorites-title">
        <h2 id="favorites-title" className={styles.sectionTitle}>
          <Icon icon={Bookmark} size={18} /> Избранное
        </h2>
        {learning.favorites.length === 0 ? (
          <Card className={styles.emptyCard}><p>Сохраняй важные темы во время чтения — они появятся здесь.</p></Card>
        ) : (
          <div className={styles.list}>
            {learning.favorites.map((item) => (
              <PressableCard key={`${item.subjectId}/${item.sectionId}/${item.materialId}`} onClick={() => navigate(`/materials/${item.subjectId}/${item.sectionId}/${item.materialId}`)} className={styles.favoriteRow}>
                <div>
                  <div className={styles.favoriteName}>{item.materialTitle || "Учебный материал"}</div>
                  <div className={styles.favoriteMeta}>{item.subjectTitle || item.subjectId}</div>
                </div>
                <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
              </PressableCard>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
