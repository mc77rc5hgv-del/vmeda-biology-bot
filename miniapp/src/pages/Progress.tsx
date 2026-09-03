import { useQuery } from "@tanstack/react-query";
import { fetchSubjects } from "../lib/api";
import { useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";

/** Экран "Прогресс" — сводка готовности по всем предметам сразу. Источник формулы готовности —
 * тот же backend-расчёт §13 ТЗ, который уже отдаёт SubjectSummary.readiness; экран лишь сводит
 * значения в один список, не пересчитывает их сам. */
export function ProgressPage() {
  useTelegramBackButton(null); // раздел нижней навигации

  const subjectsQuery = useQuery({ queryKey: ["subjects"], queryFn: fetchSubjects });

  if (subjectsQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={24} width="50%" />
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} height={56} radius="16px" />
        ))}
      </div>
    );
  }

  if (subjectsQuery.isError || !subjectsQuery.data) {
    return (
      <div className="screen">
        <StateMessage title="Не удалось загрузить прогресс" onRetry={() => subjectsQuery.refetch()} />
      </div>
    );
  }

  const openSubjects = subjectsQuery.data.filter((s) => !s.locked);
  const needsAttention = [...openSubjects].sort((a, b) => (a.readiness ?? 0) - (b.readiness ?? 0)).slice(0, 3);

  return (
    <div className="screen">
      <h1 style={{ fontSize: 20, fontWeight: 700 }}>Прогресс</h1>

      <Card>
        <span style={{ fontSize: 13, fontWeight: 700, color: "var(--ink-secondary)" }}>
          🔁 Пора повторить
        </span>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
          {needsAttention.map((subject) => (
            <div key={subject.id} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                <span>{subject.title}</span>
                <span style={{ color: "var(--ink-secondary)" }}>{subject.readiness ?? 0}%</span>
              </div>
              <ProgressBar percent={subject.readiness ?? 0} color={`var(--subject-${subject.accent})`} />
            </div>
          ))}
        </div>
      </Card>

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {openSubjects.map((subject) => (
          <Card key={subject.id} style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, fontWeight: 600 }}>
              <span>{subject.title}</span>
              <span style={{ color: "var(--ink-secondary)", fontWeight: 500 }}>{subject.readiness ?? 0}%</span>
            </div>
            <ProgressBar percent={subject.readiness ?? 0} color={`var(--subject-${subject.accent})`} />
          </Card>
        ))}
      </div>
    </div>
  );
}
