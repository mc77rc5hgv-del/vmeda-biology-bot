import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation } from "react-router-dom";
import { ArrowLeft, Clock3, LockKeyhole } from "lucide-react";
import { enterSubject, fetchAccessStatus, hasContentSession } from "../lib/api";
import { fetchStudyPreview, type StudySample } from "../lib/apiClient";
import { subscriptionPath } from "../lib/subscriptions";
import { Icon } from "./Icon";
import { Skeleton } from "./Skeleton";
import { StateMessage } from "./StateMessage";
import { AuthenticatedImage } from "./AuthenticatedImage";
import styles from "./ExamAccessGate.module.css";

export type ExamScope = "anatomy" | "anatomy_tests" | "histology";
const scopes: ExamScope[] = ["anatomy", "anatomy_tests", "histology"];

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
  const [previewOpen, setPreviewOpen] = useState(false);
  const preview = useQuery({
    queryKey: ["study-preview"],
    queryFn: fetchStudyPreview,
    enabled: Boolean(access.data && !access.data.canOpenSubject),
  });
  const begin = useMutation({
    mutationFn: () => enterSubject(scope),
    onSuccess: (status) => {
      queryClient.setQueryData(["access", scope], status);
      for (const other of scopes) {
        if (other !== scope) void queryClient.invalidateQueries({ queryKey: ["access", other] });
      }
      for (const key of ["subjects", "subject", "section", "group", "material", "subscriptions"]) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
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

  const title = { anatomy: "Анатомия", anatomy_tests: "Тесты по анатомии", histology: "Гистология" }[scope];
  const example = scope === "histology" ? "Угадай препарат · пример" : "3 пробных вопроса";
  const samples = !preview.data ? [] : scope === "histology" ? [preview.data.histology] : preview.data.anatomy;
  const bundle = preview.data?.bundle;
  const testPass = preview.data?.test_pass;
  return (
    <main className="screen">
      <Link className={styles.back} to={scope === "anatomy_tests" ? "/subjects/anatomy" : "/"}>
        <Icon icon={ArrowLeft} size={18} /> {scope === "anatomy_tests" ? "К анатомии" : "Все предметы"}
      </Link>
      <section className={styles.panel} aria-labelledby="exam-access-title">
        <span className={styles.mark}><Icon icon={status.trialAvailable ? Clock3 : LockKeyhole} size={22} /></span>
        <h1 id="exam-access-title">{title}</h1>
        {status.trialAvailable ? (
          <>
            <p>Посмотри пример или открой всю анатомию и гистологию на {status.trialDurationHours ?? 12} часов. Один таймер для бота и Mini App, он начнётся по кнопке.</p>
            <button type="button" className={styles.secondary} aria-expanded={previewOpen} onClick={() => setPreviewOpen(value => !value)}>{example}</button>
            {previewOpen && (samples.length ? <StudyPreview samples={samples} /> : preview.isError
              ? <StateMessage title="Не удалось загрузить пример" onRetry={() => void preview.refetch()} />
              : <Skeleton height={140} radius="12px" />)}
            <button type="button" className={styles.primary} disabled={begin.isPending} onClick={() => begin.mutate()}>
              {begin.isPending ? "Открываем…" : `Попробовать бесплатно на ${status.trialDurationHours ?? 12} часов`}
            </button>
            {begin.isError && <p role="alert">Не удалось открыть доступ. Попробуй ещё раз.</p>}
          </>
        ) : (
          <>
            <p><strong>Пробный доступ закончился.</strong> Ответы и работа над ошибками сохранены. Можно продолжить по подписке{scope === "anatomy" ? "." : " или пригласить двух однокурсников."}</p>
            <div className={styles.actions}>
              <Link className={styles.primary} to={subscriptionPath(scope, pathname, bundle?.id)}>
                {bundle ? `Анатомия и гистология на 14 дней · ${bundle.price_rub} ₽` : "Выбрать подписку"}
              </Link>
              {scope === "anatomy_tests" && testPass && <Link className={styles.secondary} to={subscriptionPath(scope, pathname, testPass.id)}>
                Тесты по анатомии на 7 дней · {testPass.price_rub} ₽
              </Link>}
              {scope !== "anatomy" && <Link className={styles.secondary} to="/profile/referrals">Пригласить однокурсников</Link>}
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

function StudyPreview({samples}: {samples: StudySample[]}) {
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState<number | null>(null);
  const sample = samples[index];
  return <section className={styles.sample} aria-label="Пробное задание">
    <p>{samples.length > 1 && `${index + 1} из ${samples.length} · `}<strong>{sample.question}</strong></p>
    {sample.image_url && <AuthenticatedImage src={sample.image_url} alt="Микрофотография для определения препарата" className={styles.sampleImage} />}
    {answer === null ? <div className={styles.options}>{sample.options.map((label, option) =>
      <button key={label} type="button" className={styles.secondary} onClick={() => setAnswer(option)}>{label}</button>
    )}</div> : <>
      <p role="status"><strong>{answer === sample.correct ? "Верно" : "Правильный ответ"} — {sample.options[sample.correct]}.</strong> {sample.explanation}</p>
      {index + 1 < samples.length && <button className={styles.secondary} type="button" onClick={() => {setIndex(index + 1); setAnswer(null);}}>Следующий вопрос</button>}
    </>}
  </section>;
}
