import { isSubjectOnCourse } from "../lib/subjectCourses";
import { useQuery } from "@tanstack/react-query";
import { fetchLearningState, fetchMe, fetchSubjects } from "../lib/api";
import { useUiStore, useAuthStore } from "../lib/store";
import { stepFromPath, useLastStepStore } from "../lib/lastStep";
import { useTelegramBackButton } from "../lib/telegram";
import { TopBar } from "../components/TopBar";
import { StatsBar } from "../components/StatsBar";
import { ContinueCard } from "../components/ContinueCard";
import { QuickActions } from "../components/QuickActions";
import { CourseTabs } from "../components/CourseTabs";
import { SubjectCard } from "../components/SubjectCard";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Home.module.css";

export function HomePage() {
  useTelegramBackButton(null); // главный экран — кнопка "Назад" Telegram скрыта

  const meQuery = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState });
  const subjectsQuery = useQuery({ queryKey: ["subjects"], queryFn: fetchSubjects });

  const selectedCourse = useUiStore((s) => s.selectedCourse);
  const owner = useAuthStore((state) => String(state.profile?.userId ?? "preview"));
  const lastStep = useLastStepStore((state) => state.steps[owner]);
  const setSelectedCourse = useUiStore((s) => s.setSelectedCourse);

  const isLoading = meQuery.isLoading || learningQuery.isLoading;
  const hasError = meQuery.isError || learningQuery.isError || subjectsQuery.isError;

  if (hasError) {
    return (
      <div className="screen dashboard-screen">
        <StateMessage
          title="Не удалось загрузить главную"
          body="Попробуй ещё раз через пару секунд."
          onRetry={() => {
            meQuery.refetch();
            learningQuery.refetch();
            subjectsQuery.refetch();
          }}
        />
      </div>
    );
  }

  const subjectsForCourse = (subjectsQuery.data ?? []).filter((s) => isSubjectOnCourse(s, selectedCourse));
  const learning = learningQuery.data;
  const accuracy = learning?.quizAttempts ? Math.round((learning.quizCorrect / learning.quizAttempts) * 100) : 0;
  const last = learning?.lastMaterial;
  const serverStep = learning?.lastStep ? {...stepFromPath(learning.lastStep.path)!, updatedAt: learning.lastStep.updatedAt} : null;
  const datedSteps = [serverStep, lastStep].filter(item => item?.path);
  const chosenStep = datedSteps.sort((a, b) => Date.parse(b?.updatedAt ?? "1970-01-01") - Date.parse(a?.updatedAt ?? "1970-01-01"))[0];
  const stepNewer = chosenStep?.updatedAt && (!last || Date.parse(chosenStep.updatedAt) >= Date.parse(last.lastOpenedAt));
  const continueItem = (stepNewer ? chosenStep : null) ?? (last ? {
    subjectId: last.subjectId,
    sectionId: last.sectionId,
    materialId: last.materialId,
    subjectTitle: last.subjectTitle || (subjectsQuery.data?.find((item) => item.id === last.subjectId)?.title ?? "Предмет"),
    sectionTitle: last.sectionTitle || "Материал",
    materialTitle: last.materialTitle,
    order: last.materialOrder,
    totalInSection: last.totalInSection,
  } : null);

  return (
    <div className="screen dashboard-screen">
      {isLoading || !meQuery.data ? (
        <Skeleton height={40} radius="16px" />
      ) : (
        <TopBar user={meQuery.data} />
      )}

      {isLoading ? (
        <Skeleton height={64} radius="16px" />
      ) : (
        <StatsBar completed={learning?.completedTotal ?? 0} accuracy={accuracy} favorites={learning?.favorites.length ?? 0} />
      )}

      {learning && meQuery.data && (
        <div className="page-intro">
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>{meQuery.data.firstName}, продолжаем?</h1>
          <p style={{ fontSize: 13, color: "var(--ink-secondary)", marginTop: 4 }}>
            {learning.completedTotal ? "продолжай в своём темпе" : "начни с одного материала или теста"}
          </p>
        </div>
      )}

      {learningQuery.isLoading ? (
        <Skeleton height={130} radius="22px" />
      ) : (
        continueItem && <ContinueCard item={continueItem} />
      )}

      <section className={styles.sectionBlock} aria-labelledby="quick-actions-title">
        <div className={styles.sectionHeading}>
          <h2 id="quick-actions-title">Быстрый доступ</h2>
          <span>Всё нужное под рукой</span>
        </div>
        <QuickActions />
      </section>

      <section className={styles.sectionBlock} aria-labelledby="subjects-title">
        <div className={styles.sectionHeading}>
          <h2 id="subjects-title">Предметы</h2>
          <span>{subjectsForCourse.length} на курсе</span>
        </div>
        <CourseTabs value={selectedCourse} onChange={setSelectedCourse} />

        {subjectsQuery.isLoading ? (
          <div className={styles.skeletonGrid}>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} height={120} radius="22px" />
            ))}
          </div>
        ) : subjectsForCourse.length === 0 ? (
          <StateMessage title="Пока пусто" body="Для этого курса ещё нет предметов." />
        ) : (
          <div className={styles.subjectGrid} role="list" aria-label="Предметы">
            {subjectsForCourse.map((subject) => (
              <SubjectCard key={subject.id} subject={subject} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
