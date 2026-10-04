import { useQuery } from "@tanstack/react-query";
import { Bookmark, ChevronRight, CircleCheckBig, Target, Search, Lock } from "lucide-react";
import { useState } from "react";
import { subjectIcon } from "../lib/subjectIcons";
import { useNavigate } from "react-router-dom";
import { fetchLearningState, fetchSubjectDetail, fetchSubjects } from "../lib/api";
import { useTelegramBackButton } from "../lib/telegram";
import { Card, PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { ProgressBar } from "../components/ProgressBar";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { SubjectTheme } from "../components/SubjectTheme";
import styles from "./Progress.module.css";

export function ProgressPage() {
  useTelegramBackButton(null);
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [course, setCourse] = useState<0 | 1 | 2>(0);
  const subjectsQuery = useQuery({ queryKey: ["subjects"], queryFn: fetchSubjects });
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState });
  const detailsQuery = useQuery({
    queryKey: ["subject-totals", ...(subjectsQuery.data?.map((item) => item.id) ?? [])],
    enabled: Boolean(subjectsQuery.data),
    queryFn: async () => Promise.allSettled((subjectsQuery.data ?? []).map((item) => fetchSubjectDetail(item.id))),
    staleTime: 5 * 60_000,
  });

  if (subjectsQuery.isLoading || learningQuery.isLoading || detailsQuery.isLoading) {
    return <div className="screen"><Skeleton height={30} width="50%" />{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={72} radius="16px" />)}</div>;
  }
  if (subjectsQuery.isError || learningQuery.isError || !subjectsQuery.data || !learningQuery.data) {
    return <div className="screen"><StateMessage title="Не удалось загрузить прогресс" onRetry={() => { subjectsQuery.refetch(); learningQuery.refetch(); }} /></div>;
  }

  const totals = new Map((detailsQuery.data ?? []).flatMap((result) => result.status === "fulfilled" && result.value ? [result.value] : []).map((subject) => [
    subject!.id,
    subject!.sections.reduce((sum, section) => sum + section.itemCount, 0),
  ]));
  const learning = learningQuery.data;
  const accuracy = learning.quizAttempts ? Math.round((learning.quizCorrect / learning.quizAttempts) * 100) : 0;
  const visibleSubjects = subjectsQuery.data.filter((subject) => (!course || subject.course === course)
    && subject.title.toLocaleLowerCase("ru").includes(search.trim().toLocaleLowerCase("ru")));
  const partialTotals = detailsQuery.isError || detailsQuery.data?.some((result) => result.status === "rejected");

  return (
    <div className="screen">
      <div className="page-intro">
        <h1>Мой прогресс</h1>
        <p>Твои результаты и следующий шаг в подготовке</p>
      </div>

      <div className={styles.statsGrid}>
        <Card className={styles.statCard}>
          <Icon icon={CircleCheckBig} size={21} color="var(--success)" />
          <strong className={styles.statValue}>{learning.completedTotal}</strong>
          <span className={styles.statLabel}>тем изучено</span>
        </Card>
        <Card className={styles.statCard}>
          <Icon icon={Target} size={21} color="var(--academic-blue)" />
          <strong className={styles.statValue}>{learning.quizAttempts ? `${accuracy}%` : "—"}</strong>
          <span className={styles.statLabel}>точность ответов</span>
          <span className={styles.statHint}>{learning.quizAttempts ? `${learning.quizAttempts} ответов в тестах` : "Появится после первого ответа"}</span>
        </Card>
      </div>

      <section aria-labelledby="subjects-progress">
        <h2 id="subjects-progress" className={styles.sectionTitle}>По предметам</h2>
        <p className={styles.sectionHint}>Полоса показывает долю изученных тем.</p>
        <div className={styles.filters} aria-label="Курс">
          {([0, 1, 2] as const).map((value) => <button key={value} type="button" aria-pressed={course === value} onClick={() => setCourse(value)}>{value === 0 ? "Все предметы" : `${value} курс`}</button>)}
        </div>
        <label className={styles.search}><Icon icon={Search} size={18} /><input aria-label="Найти предмет" placeholder="Найти предмет" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
        {partialTotals && <StateMessage title="Часть показателей временно недоступна" onRetry={() => detailsQuery.refetch()} />}
        <div className={styles.list}>
          {visibleSubjects.map((subject) => {
            const completed = learning.completedBySubject[subject.id] ?? 0;
            const total = totals.get(subject.id);
            const percent = total ? Math.min(100, Math.round((completed / total) * 100)) : 0;
            const accent = `var(--subject-${subject.accent})`;
            return (
              <SubjectTheme key={subject.id} subjectId={subject.id}>
              <PressableCard onClick={() => navigate(`/subjects/${subject.id}`)} className={styles.subjectCard}>
                <div className={styles.subjectTop}>
                  <span className={styles.subjectIcon} style={{ color: accent }}><Icon icon={subjectIcon(subject.id)} size={23} /></span>
                  <div className={styles.subjectCopy}>
                  <strong className={styles.subjectName}>{subject.title}</strong>
                  <span className={styles.subjectMeta}>{total ? `${completed} из ${total} тем изучено` : completed ? `${completed} тем изучено` : "Пока нет изученных тем"}</span>
                  {subject.locked && <span className={styles.accessHint}><Icon icon={Lock} size={12} />{subject.lockedReason || "Доступ ограничен"}</span>}
                  </div>
                  <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
                </div>
                {total ? <div className={styles.progressRow}><ProgressBar percent={percent} color={accent} label={`Изучено тем по предмету ${subject.title}: ${percent}%`} /><strong style={{ color: accent }}>{percent}%</strong></div> : <p className={styles.subjectMeta}>Общее количество тем пока недоступно</p>}
              </PressableCard>
              </SubjectTheme>
            );
          })}
          {!visibleSubjects.length && <Card className={styles.emptyCard}><p>Предметы не найдены. Попробуй другое название или выбери все курсы.</p></Card>}
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
