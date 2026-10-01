import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronRight, GraduationCap, Microscope, RotateCcw, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { ZoomableMicrograph } from "../components/ZoomableMicrograph";
import {
  fetchHistologyCatalog,
  fetchHistologyPractical,
  fetchHistologyStats,
  gradeHistologyAnswer,
  revealHistologyAnswer,
} from "../lib/apiClient";
import { hapticSelection, useTelegramBackButton } from "../lib/telegram";
import type { HistologyPracticalQuestion, HistologySpecimenSummary } from "../lib/types";
import styles from "./HistologyExam.module.css";

type Scope = "all" | "mistakes";

export function HistologyExamPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [session, setSession] = useState<{ scope: Scope; items: HistologyPracticalQuestion[] } | null>(null);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState<(HistologySpecimenSummary & { protocol: string }) | null>(null);
  const [sessionKnown, setSessionKnown] = useState(0);
  const [loadingAction, setLoadingAction] = useState(false);

  useTelegramBackButton(() => session ? setSession(null) : navigate("/subjects/histology"));

  const catalogQuery = useQuery({ queryKey: ["histology-catalog"], queryFn: fetchHistologyCatalog });
  const statsQuery = useQuery({ queryKey: ["histology-stats"], queryFn: fetchHistologyStats });

  const filteredGroups = useMemo(() => {
    const groups = catalogQuery.data?.groups ?? [];
    const needle = search.trim().toLocaleLowerCase("ru");
    if (!needle) return groups;
    return groups
      .map((group) => ({
        ...group,
        specimens: group.specimens.filter((item) =>
          `${item.number} ${item.title} ${item.stain ?? ""}`.toLocaleLowerCase("ru").includes(needle),
        ),
      }))
      .filter((group) => group.specimens.length > 0);
  }, [catalogQuery.data, search]);

  const startSession = async (scope: Scope) => {
    setLoadingAction(true);
    try {
      const items = await fetchHistologyPractical(scope, 10);
      setSession({ scope, items });
      setIndex(0);
      setAnswer(null);
      setSessionKnown(0);
    } finally {
      setLoadingAction(false);
    }
  };

  const current = session?.items[index];
  const finished = Boolean(session && index >= session.items.length);

  const reveal = async () => {
    if (!current) return;
    setLoadingAction(true);
    try { setAnswer(await revealHistologyAnswer(current.id)); }
    finally { setLoadingAction(false); }
  };

  const grade = async (known: boolean) => {
    if (!current || !session) return;
    setLoadingAction(true);
    try {
      await gradeHistologyAnswer(current.id, known, session.scope);
      if (known) setSessionKnown((value) => value + 1);
      setIndex((value) => value + 1);
      setAnswer(null);
      queryClient.invalidateQueries({ queryKey: ["histology-stats"] });
      hapticSelection();
    } finally {
      setLoadingAction(false);
    }
  };

  if (catalogQuery.isLoading) {
    return <div className="screen"><Skeleton height={190} radius="24px" /><Skeleton height={112} radius="20px" /></div>;
  }
  if (catalogQuery.isError || !catalogQuery.data) {
    return <div className="screen"><StateMessage title="Не удалось открыть ЭКЗАМЕН" onRetry={() => catalogQuery.refetch()} /></div>;
  }

  if (session) {
    return (
      <div className={["screen", styles.examScreen].join(" ")}>
        <button type="button" className={styles.backButton} onClick={() => setSession(null)}>
          <Icon icon={ArrowLeft} size={18} /> К каталогу
        </button>

        {session.items.length === 0 ? (
          <StateMessage
            icon={RotateCcw}
            title={session.scope === "mistakes" ? "Ошибок для повторения нет" : "Тренажёр пока недоступен"}
            body={session.scope === "mistakes" ? "Ошибочные препараты появятся здесь после первой попытки." : undefined}
          />
        ) : finished ? (
          <div className={styles.resultCard}>
            <span className={styles.resultIcon}><Icon icon={GraduationCap} size={28} /></span>
            <p className={styles.eyebrow}>Практический зачёт завершён</p>
            <h1>{sessionKnown} из {session.items.length}</h1>
            <p>Результат сохранён. Нераспознанные препараты уже добавлены в работу над ошибками.</p>
            <button type="button" onClick={() => startSession(session.scope)}>Пройти ещё раз</button>
            <button type="button" className={styles.secondaryButton} onClick={() => setSession(null)}>Вернуться в ЭКЗАМЕН</button>
          </div>
        ) : current ? (
          <>
            <div className={styles.examHead}>
              <div>
                <p className={styles.eyebrow}>{session.scope === "mistakes" ? "Работа над ошибками" : "Практический зачёт"}</p>
                <h1>Определите препарат</h1>
              </div>
              <span>{index + 1}/{session.items.length}</span>
            </div>
            <div className={styles.progressTrack}><i style={{ width: `${((index + 1) / session.items.length) * 100}%` }} /></div>
            <ZoomableMicrograph
              key={current.id}
              src={current.imageUrl}
              alt="Микрофотография для определения препарата"
            />

            {!answer ? (
              <button type="button" className={styles.primaryButton} disabled={loadingAction} onClick={reveal}>
                {loadingAction ? "Открываем…" : "Показать ответ"}
              </button>
            ) : (
              <div className={styles.answerCard}>
                <p className={styles.eyebrow}>Правильный ответ</p>
                <h2>{answer.title}</h2>
                <div className={styles.metaLine}>
                  {answer.stain && <span>{answer.stain}</span>}
                  {answer.magnification && <span>×{answer.magnification}</span>}
                </div>
                <p className={styles.protocolPreview}>{answer.protocol.split(/\n\s*\n/)[0]}</p>
                <p className={styles.selfGrade}>Удалось определить до подсказки?</p>
                <div className={styles.gradeGrid}>
                  <button type="button" disabled={loadingAction} onClick={() => grade(false)}><Icon icon={X} size={18} /> Не узнал</button>
                  <button type="button" disabled={loadingAction} onClick={() => grade(true)}><Icon icon={Check} size={18} /> Узнал</button>
                </div>
              </div>
            )}
          </>
        ) : null}
      </div>
    );
  }

  const stats = statsQuery.data;
  return (
    <div className={["screen", styles.examScreen].join(" ")}>
      <section className={styles.hero}>
        <div className={styles.heroTop}>
          <span className={styles.heroIcon}><Icon icon={Microscope} size={24} /></span>
          <span className={styles.heroBadge}>71 препарат</span>
        </div>
        <p className={styles.eyebrow}>Гистология</p>
        <h1>ЭКЗАМЕН</h1>
        <p>Единое место для микрофотографий, теории, практического зачёта и работы над ошибками.</p>
        <div className={styles.statsGrid}>
          <div><strong>{stats?.mastered ?? 0}</strong><span>освоено</span></div>
          <div><strong>{stats?.accuracy ?? 0}%</strong><span>точность</span></div>
          <div><strong>{stats?.activeMistakes ?? 0}</strong><span>ошибок</span></div>
        </div>
      </section>

      <div className={styles.actions}>
        <button type="button" disabled={loadingAction} onClick={() => startSession("all")}>
          <span><Icon icon={GraduationCap} size={21} /></span>
          <div><strong>Практический зачёт</strong><small>10 случайных микрофотографий</small></div>
          <Icon icon={ChevronRight} size={18} />
        </button>
        <button type="button" disabled={loadingAction} onClick={() => startSession("mistakes")}>
          <span className={styles.mistakeIcon}><Icon icon={RotateCcw} size={20} /></span>
          <div><strong>Работа над ошибками</strong><small>{stats?.activeMistakes ?? 0} препаратов для повторения</small></div>
          <Icon icon={ChevronRight} size={18} />
        </button>
      </div>

      <div className={styles.catalogHead}>
        <div><p className={styles.eyebrow}>Атлас</p><h2>Каталог препаратов</h2></div>
        <span>{catalogQuery.data.totalSpecimens}</span>
      </div>
      <label className={styles.searchBox}>
        <Icon icon={Search} size={18} />
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Найти препарат или окраску" />
      </label>

      <div className={styles.catalog}>
        {filteredGroups.map((group) => (
          <section key={group.id} className={styles.group}>
            <div className={styles.groupHead}><h3>{group.menuTitle}</h3><span>{group.specimens.length}</span></div>
            {group.specimens.map((specimen) => (
              <button key={specimen.id} type="button" onClick={() => navigate(`/histology/specimens/${specimen.id}`)}>
                <span className={styles.specimenNumber}>{specimen.number}</span>
                <div>
                  <strong>{specimen.title}</strong>
                  <small>{[specimen.stain, specimen.magnification ? `×${specimen.magnification}` : null].filter(Boolean).join(" · ")}</small>
                </div>
                <Icon icon={ChevronRight} size={17} />
              </button>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
