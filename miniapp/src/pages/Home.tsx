import { useQuery } from "@tanstack/react-query";
import { fetchContinueItem, fetchDashboard, fetchMe, fetchSubjects } from "../lib/api";
import { useUiStore } from "../lib/store";
import { useTelegramBackButton } from "../lib/telegram";
import { TopBar } from "../components/TopBar";
import { StatsBar } from "../components/StatsBar";
import { ContinueCard } from "../components/ContinueCard";
import { QuickActions } from "../components/QuickActions";
import { CourseTabs } from "../components/CourseTabs";
import { SubjectCard } from "../components/SubjectCard";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";

function greetingTime(minutesLeft: number): string {
  if (minutesLeft <= 0) return "дневная цель уже выполнена";
  return `сегодня осталось ${minutesLeft} минут`;
}

export function HomePage() {
  useTelegramBackButton(null); // главный экран — кнопка "Назад" Telegram скрыта

  const meQuery = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const dashboardQuery = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard });
  const continueQuery = useQuery({ queryKey: ["continue"], queryFn: fetchContinueItem });
  const subjectsQuery = useQuery({ queryKey: ["subjects"], queryFn: fetchSubjects });

  const selectedCourse = useUiStore((s) => s.selectedCourse);
  const setSelectedCourse = useUiStore((s) => s.setSelectedCourse);

  const isLoading = meQuery.isLoading || dashboardQuery.isLoading;
  const hasError = meQuery.isError || dashboardQuery.isError || subjectsQuery.isError;

  if (hasError) {
    return (
      <div className="screen">
        <StateMessage
          title="Не удалось загрузить главную"
          body="Попробуй ещё раз через пару секунд."
          onRetry={() => {
            meQuery.refetch();
            dashboardQuery.refetch();
            subjectsQuery.refetch();
          }}
        />
      </div>
    );
  }

  const subjectsForCourse = (subjectsQuery.data ?? []).filter((s) => s.course === selectedCourse);

  return (
    <div className="screen">
      {isLoading || !meQuery.data ? (
        <Skeleton height={40} radius="16px" />
      ) : (
        <TopBar user={meQuery.data} />
      )}

      {isLoading || !dashboardQuery.data ? (
        <Skeleton height={64} radius="16px" />
      ) : (
        <StatsBar stats={dashboardQuery.data} />
      )}

      {dashboardQuery.data && meQuery.data && (
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>{meQuery.data.firstName}, продолжаем?</h1>
          <p style={{ fontSize: 13, color: "var(--ink-secondary)", marginTop: 4 }}>
            {greetingTime(dashboardQuery.data.minutesLeftToday)}
          </p>
        </div>
      )}

      {continueQuery.isLoading ? (
        <Skeleton height={130} radius="22px" />
      ) : (
        continueQuery.data && <ContinueCard item={continueQuery.data} />
      )}

      <QuickActions />

      <CourseTabs value={selectedCourse} onChange={setSelectedCourse} />

      {subjectsQuery.isLoading ? (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} height={120} radius="22px" />
          ))}
        </div>
      ) : subjectsForCourse.length === 0 ? (
        <StateMessage title="Пока пусто" body="Для этого курса ещё нет предметов." />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }} role="list" aria-label="Предметы">
          {subjectsForCourse.map((subject) => (
            <SubjectCard key={subject.id} subject={subject} />
          ))}
        </div>
      )}
    </div>
  );
}
