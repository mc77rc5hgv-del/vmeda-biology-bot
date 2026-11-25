import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { ArrowLeft, Clock3, LockKeyhole } from "lucide-react";
import { enterSubject, fetchAccessStatus, hasContentSession } from "../lib/api";
import { subscriptionPath } from "../lib/subscriptions";
import { Icon } from "./Icon";
import { Skeleton } from "./Skeleton";
import { StateMessage } from "./StateMessage";
import styles from "./ExamAccessGate.module.css";

export type ExamScope = "anatomy_tests" | "histology";

const deadlineFormat = new Intl.DateTimeFormat("ru-RU", {
  timeZone: "Europe/Moscow", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit",
});

export function ExamAccessGate({ scope, children }: { scope?: ExamScope; children: ReactNode }) {
  if (!scope || !hasContentSession()) return <>{children}</>;
  return <ExamAccessContent key={scope} scope={scope}>{children}</ExamAccessContent>;
}

function ExamAccessContent({ scope, children }: { scope: ExamScope; children: ReactNode }) {
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  const access = useQuery({
    queryKey: ["access", scope],
    queryFn: () => fetchAccessStatus(scope),
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
  });
  const begin = useMutation({
    mutationFn: () => enterSubject(scope),
    onSuccess: (status) => {
      queryClient.setQueryData(["access", scope], status);
      const other = scope === "histology" ? "anatomy_tests" : "histology";
      void queryClient.invalidateQueries({ queryKey: ["access", other] });
    },
  });
  const refresh = access.refetch;
  const expiresAt = access.data?.trialExpiresAt;
  const [expiredDeadline, setExpiredDeadline] = useState<string | null>(null);
  useEffect(() => {
    if (!expiresAt) return;
    const remaining = Date.parse(expiresAt) - Date.now();
    const timer = window.setTimeout(() => {
      setExpiredDeadline(expiresAt);
      void refresh();
    }, Math.max(remaining + 200, 0));
    return () => window.clearTimeout(timer);
  }, [expiresAt, refresh]);

  const status = access.data;
  if (access.isPending) return <div className="screen"><Skeleton height={120} radius="18px" /></div>;
  if (!status) {
    return <div className="screen"><StateMessage title="Не удалось проверить доступ" onRetry={() => void refresh()} /></div>;
  }
  const trialExpired = expiresAt != null && expiresAt === expiredDeadline;
  if (status.canOpenSubject && !trialExpired) {
    return (
      <>
        {expiresAt && (
          <p className={styles.notice}>
            <Icon icon={Clock3} size={16} />
            Пробный доступ до {deadlineFormat.format(new Date(expiresAt))} МСК
          </p>
        )}
        {children}
      </>
    );
  }

  const title = scope === "histology" ? "Гистология" : "Тесты по анатомии";
  const subjectId = scope === "histology" ? scope : "anatomy";
  return (
    <main className="screen">
      <Link className={styles.back} to={subjectId === "histology" ? "/" : "/subjects/anatomy"}>
        <Icon icon={ArrowLeft} size={18} /> {subjectId === "histology" ? "Все предметы" : "К анатомии"}
      </Link>
      <section className={styles.panel} aria-labelledby="exam-access-title">
        <span className={styles.mark}><Icon icon={status.trialAvailable ? Clock3 : LockKeyhole} size={22} /></span>
        <h1 id="exam-access-title">{title}</h1>
        {status.trialAvailable ? (
          <>
            <p>Попробуй оба раздела бесплатно. У тебя будет {status.trialDurationHours ?? 24} часа на тесты по анатомии и материалы по гистологии.</p>
            <button type="button" className={styles.primary} disabled={begin.isPending} onClick={() => begin.mutate()}>
              {begin.isPending ? "Открываем…" : "Начать пробный доступ"}
            </button>
            {begin.isError && <p role="alert">Не удалось открыть доступ. Попробуй ещё раз.</p>}
          </>
        ) : (
          <>
            <p><strong>Пробный доступ закончился.</strong> Оформи подходящую подписку или пригласи двух однокурсников по своей ссылке в этом месяце.</p>
            <div className={styles.actions}>
              <Link className={styles.primary} to={subscriptionPath(scope, pathname)}>Выбрать подписку</Link>
              <Link className={styles.secondary} to="/profile/referrals">Пригласить однокурсников</Link>
            </div>
            <button type="button" className={styles.refresh} disabled={access.isFetching} onClick={() => void refresh()}>
              {access.isFetching ? "Проверяем…" : "Проверить доступ"}
            </button>
          </>
        )}
      </section>
    </main>
  );
}
