import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BookOpen, Check, ChevronRight, ClipboardList, GraduationCap, Images, Microscope, RotateCcw, ScanSearch, Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { ZoomableMicrograph, type MicrographHandle } from "../components/ZoomableMicrograph";
import {
  fetchHistologyCatalog,
  fetchHistologyPractical,
  fetchHistologyStats,
  gradeHistologyAnswer,
  revealHistologyAnswer,
} from "../lib/apiClient";
import { filterHistologyGroups, type HistologyCatalogLocation } from "../lib/histologyCatalog";
import { hapticSelection, useTelegramBackButton } from "../lib/telegram";
import type { HistologyPracticalQuestion } from "../lib/types";
import styles from "./HistologyExam.module.css";

type Scope = "all" | "mistakes";

export function HistologyExamPage() {
  const navigate = useNavigate();
  const links = [
    { title: "Препараты", to: "specimens", icon: Microscope },
    { title: "Тесты", to: "tests", icon: ClipboardList },
    { title: "Теоретические вопросы", to: "theory", icon: BookOpen },
    { title: "УГАДАЙ ПРЕПАРАТ", to: "guess", icon: ScanSearch },
  ];
  useTelegramBackButton(() => navigate("/subjects/histology"));
  return (
    <div className={["screen", styles.examScreen].join(" ")}>
      <button type="button" className={styles.backButton} onClick={() => navigate("/subjects/histology")}>
        <Icon icon={ArrowLeft} size={18} /> Гистология
      </button>
      <h1>Экзамен</h1>
      <div className={styles.actions}>
        {links.map(({ title, to, icon }) => (
          <button key={to} type="button" onClick={() => navigate(`/histology/exam/${to}`)}>
            <span><Icon icon={icon} size={21} /></span>
            <strong>{title}</strong>
            <Icon icon={ChevronRight} size={18} />
          </button>
        ))}
      </div>
    </div>
  );
}

export function HistologyCatalogPage({ diagnostics = false }: { diagnostics?: boolean }) {
  const navigate = useNavigate();
  const { search: catalogSearch } = useLocation();
  const [params, setParams] = useSearchParams();
  const searchInput = useRef<HTMLInputElement>(null);
  const back = diagnostics ? "/subjects/histology" : "/histology/exam";
  const scope = diagnostics ? "diagnostics" : "exam";
  const catalogPath = diagnostics ? "/histology/diagnostics" : "/histology/exam/specimens";
  useTelegramBackButton(() => navigate(back));
  const catalogQuery = useQuery({ queryKey: ["histology-catalog", scope], queryFn: () => fetchHistologyCatalog(scope) });
  const catalog = catalogQuery.data;

  const groups = catalog?.groups ?? [];
  const filteredGroups = filterHistologyGroups(groups, params);
  const count = filteredGroups.reduce((sum, group) => sum + group.specimens.length, 0);
  const search = params.get("q") ?? "";
  const selectedGroup = groups.find((group) => group.id === params.get("group"));
  const filtered = Boolean(search.trim() || selectedGroup);

  function updateFilter(key: "group" | "q", value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  }

  function openSpecimen(id: string) {
    const state: HistologyCatalogLocation = { catalogPath, catalogSearch };
    navigate(`/histology/specimens/${encodeURIComponent(id)}?scope=${scope}`, { state });
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  return (
    <div className={["screen", styles.examScreen].join(" ")}>
      <button type="button" className={styles.backButton} onClick={() => navigate(back)}>
        <Icon icon={ArrowLeft} size={18} /> {diagnostics ? "Гистология" : "Экзамен"}
      </button>
      <header className={styles.catalogHead}>
        <div>
          <h1>{diagnostics ? "Диагностики" : "Препараты"}</h1>
          {catalog && <p>Препаратов: {catalog.totalSpecimens} · диагностик: {groups.length}</p>}
        </div>
        <span className={styles.catalogIcon}><Icon icon={Microscope} size={27} /></span>
      </header>
      {catalogQuery.isLoading ? <Skeleton height={190} radius="22px" /> : catalogQuery.isError || !catalog ? (
        <StateMessage title="Не удалось загрузить препараты" onRetry={() => catalogQuery.refetch()} />
      ) : (
        <>
          <div className={styles.catalogFilters}>
            <div className={styles.searchBox} role="search">
              <Icon icon={Search} size={20} />
              <input ref={searchInput} type="search" value={search} maxLength={160}
                onChange={(event) => updateFilter("q", event.target.value)}
                aria-label="Номер, название или окраска" placeholder="Номер, название или окраска" />
              {search && (
                <button type="button" aria-label="Очистить поиск" onClick={() => {
                  updateFilter("q", "");
                  searchInput.current?.focus();
                }}><Icon icon={X} size={18} /></button>
              )}
            </div>
            <div className={styles.catalogGroupFilter} role="group" aria-label="Выбор диагностики">
              <button type="button" aria-pressed={!selectedGroup} onClick={() => updateFilter("group", "")}>Все</button>
              {groups.map((group) => (
                <button type="button" key={group.id} aria-label={group.title}
                  aria-pressed={selectedGroup?.id === group.id} onClick={() => updateFilter("group", group.id)}>
                  {group.title.match(/№\d+/)?.[0] ?? group.title}
                </button>
              ))}
            </div>
            {filtered && <p role="status" className={styles.catalogCount}>Найдено: {count} из {catalog.totalSpecimens}</p>}
          </div>
          {count === 0 ? (
            <StateMessage icon={Search} title="Препараты не найдены" body="Попробуйте другое название, номер или диагностику."
              onRetry={() => setParams({}, { replace: true })} actionLabel="Сбросить фильтры" />
          ) : (
            <div className={styles.catalog}>
              {filteredGroups.map((group) => {
                const [title, topic] = group.title.split(": ");
                return (
                  <section key={group.id} className={styles.group}>
                    <header className={styles.groupHead}>
                      <div><h2>{title}</h2>{topic && <p>{topic}</p>}</div>
                      <span><span className="visually-hidden">Препаратов: </span>{group.specimens.length}</span>
                    </header>
                    {diagnostics && (
                      <button type="button" aria-label={`Угадай препарат · ${title}`}
                        onClick={() => navigate(`/histology/diagnostics/${encodeURIComponent(group.id)}/guess`)}>
                        <span className={styles.specimenNumber}><Icon icon={ScanSearch} size={20} /></span>
                        <span className={styles.specimenLabel}><strong>Угадай препарат</strong></span>
                        <Icon icon={ChevronRight} size={18} />
                      </button>
                    )}
                    {group.specimens.map((specimen) => (
                      <button key={specimen.id} type="button" onClick={() => openSpecimen(specimen.id)}>
                        <span className={styles.specimenNumber}><span className="visually-hidden">Препарат №</span>{specimen.number}</span>
                        <span className={styles.specimenLabel}>
                          <strong>{specimen.title}</strong>
                          <span className={styles.specimenMeta}>
                            {specimen.stain && <span>{specimen.stain}</span>}
                            {specimen.magnification && <span>×{specimen.magnification}</span>}
                            <span className={styles.imageCount}>
                              <Icon icon={Images} size={14} />
                              <span className="visually-hidden">Изображений: </span>{specimen.imageCount}
                            </span>
                          </span>
                        </span>
                        <Icon icon={ChevronRight} size={18} />
                      </button>
                    ))}
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function HistologyGuessPage() {
  const { diagnosticId } = useParams();
  return <HistologyGuessTrainer key={diagnosticId ?? "exam"} diagnosticId={diagnosticId} />;
}

function HistologyGuessTrainer({ diagnosticId }: { diagnosticId?: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const catalogScope = diagnosticId ? "diagnostics" : "exam";
  const back = diagnosticId ? `/histology/diagnostics?group=${encodeURIComponent(diagnosticId)}` : "/histology/exam";
  const [session, setSession] = useState<{ scope: Scope; items: HistologyPracticalQuestion[] } | null>(null);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState<Awaited<ReturnType<typeof revealHistologyAnswer>> | null>(null);
  const [sessionKnown, setSessionKnown] = useState(0);
  const [loadingAction, setLoadingAction] = useState(false);
  const busy = useRef(false);
  const lastDiagnosticAttempt = useRef<string | null>(null);
  const viewer = useRef<MicrographHandle>(null);
  const questionHeading = useRef<HTMLHeadingElement>(null);
  const answerHeading = useRef<HTMLHeadingElement>(null);
  const [pendingGrade, setPendingGrade] = useState<boolean | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const backToTrainer = () => {
    setSession(null);
    setActionError(null);
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  useTelegramBackButton(() => {
    if (viewer.current?.closeFullscreen()) return;
    if (session) backToTrainer();
    else navigate(back);
  });

  const catalogQuery = useQuery({ queryKey: ["histology-catalog", catalogScope], queryFn: () => fetchHistologyCatalog(catalogScope) });
  const statsQuery = useQuery({ queryKey: ["histology-stats"], queryFn: fetchHistologyStats, enabled: !diagnosticId });
  const groups = catalogQuery.data?.groups ?? [];
  const diagnostic = groups.find((group) => group.id === diagnosticId);
  const diagnosticTitle = diagnostic?.title.split(": ")[0];

  const startSession = async (scope: Scope) => {
    setLoadingAction(true);
    setActionError(null);
    try {
      const items = await fetchHistologyPractical(diagnosticId ?? scope, diagnosticId ? 30 : 10, catalogScope);
      setPendingGrade(null);
      setSession({ scope, items });
      setIndex(0);
      setAnswer(null);
      setSessionKnown(0);
    } catch {
      setActionError('Не удалось начать тренировку. Повтори попытку.');
    } finally {
      setLoadingAction(false);
    }
  };

  const current = session?.items[index];
  const finished = Boolean(session && index >= session.items.length);

  useEffect(() => {
    if (session) {
      window.scrollTo({ top: 0, behavior: "instant" });
      questionHeading.current?.focus({ preventScroll: true });
    }
  }, [session, index]);

  useEffect(() => {
    const heading = answerHeading.current;
    if (!answer || !heading) return;
    heading.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 899px)").matches) {
      heading.closest("article")?.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }, [answer]);

  const reveal = async () => {
    if (!current) return;
    setLoadingAction(true);
    setActionError(null);
    try { setAnswer(await revealHistologyAnswer(current.id, current.photoId, catalogScope)); }
    catch { setActionError('Не удалось показать ответ. Повтори попытку.'); }
    finally { setLoadingAction(false); }
  };

  const grade = async (known: boolean) => {
    if (!current || !session || !answer || busy.current || (pendingGrade !== null && pendingGrade !== known)) return;
    if (diagnosticId && lastDiagnosticAttempt.current === current.attemptId) return;
    busy.current = true;
    setPendingGrade(known);
    setLoadingAction(true);
    setActionError(null);
    try {
      if (diagnosticId) {
        lastDiagnosticAttempt.current = current.attemptId;
      } else {
        await gradeHistologyAnswer(current.id, known, session.scope, current.attemptId);
        queryClient.invalidateQueries({ queryKey: ["histology-stats"] });
        queryClient.invalidateQueries({ queryKey: ["learning"] });
        queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      }
      setPendingGrade(null);
      if (known) setSessionKnown((value) => value + 1);
      setIndex((value) => value + 1);
      setAnswer(null);
      hapticSelection();
    } catch {
      setActionError('Не удалось подтвердить сохранение ответа. Повтори ту же оценку: попытка не будет задвоена.');
    } finally {
      busy.current = false;
      setLoadingAction(false);
    }
  };

  if (!session && catalogQuery.isLoading) {
    return <div className="screen"><Skeleton height={190} radius="24px" /><Skeleton height={112} radius="20px" /></div>;
  }
  if (!session && (catalogQuery.isError || !catalogQuery.data)) {
    return <div className="screen"><StateMessage title="Не удалось открыть тренажёр" onRetry={() => catalogQuery.refetch()} /></div>;
  }
  if (diagnosticId && !diagnostic) {
    return (
      <div className="screen">
        <StateMessage title="Диагностика не найдена" onRetry={() => navigate("/histology/diagnostics")} actionLabel="К диагностикам" />
      </div>
    );
  }

  if (session) {
    return (
      <div className={["screen", styles.examScreen].join(" ")}>
        {actionError && !current && <p role="alert">{actionError}</p>}
        <button type="button" className={styles.backButton} onClick={backToTrainer}>
          <Icon icon={ArrowLeft} size={18} /> К тренажёру
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
            <p className={styles.eyebrow}>{diagnosticTitle ?? "Практический зачёт завершён"}</p>
            <h1>{sessionKnown} из {session.items.length}</h1>
            <p>{diagnosticId ? "Препаратов определено верно" : "Результат сохранён. Нераспознанные препараты уже добавлены в работу над ошибками."}</p>
            <button type="button" disabled={loadingAction} onClick={() => startSession(session.scope)}>Пройти ещё раз</button>
            <button type="button" className={styles.secondaryButton}
              onClick={diagnosticId ? () => navigate(back) : backToTrainer}>{diagnosticId ? "К диагностике" : "К тренажёру"}</button>
          </div>
        ) : current ? (
          <>
            <div className={styles.examHead}>
              <div>
                <p className={styles.eyebrow}>{diagnosticTitle ?? (session.scope === "mistakes" ? "Работа над ошибками" : "Практический зачёт")}</p>
                <h1 ref={questionHeading} tabIndex={-1}>Определите препарат</h1>
              </div>
              <span>{index + 1}/{session.items.length}</span>
            </div>
            <div className={styles.progressTrack}><i style={{ width: `${((index + 1) / session.items.length) * 100}%` }} /></div>
            <div className={styles.guessRound}>
              <div className={styles.guessImage}>
                <ZoomableMicrograph
                  key={current.attemptId}
                  ref={viewer}
                  src={current.imageUrl}
                  alt="Микрофотография для определения препарата"
                />
              </div>
              {answer && (
                <article className={`${styles.answerCard} ${styles.guessAnswer}`}>
                  <p className={styles.eyebrow}>Правильный ответ</p>
                  <h2 ref={answerHeading} tabIndex={-1}>{answer.title}</h2>
                  <div className={styles.metaLine}>
                    {answer.stain && <span>По перечню: {answer.stain}</span>}
                    {answer.magnification && <span>×{answer.magnification}</span>}
                  </div>
                  <p className={styles.protocolPreview}>{answer.protocol.split(/\n\s*\n/)[0]}</p>
                  {answer.guessImageNote && <p className={`${styles.protocolPreview} ${styles.guessCaption}`}>{answer.guessImageNote}</p>}
                </article>
              )}
              <div className={styles.guessActions}>
                {actionError && <p className={styles.guessError} role="alert">{actionError}</p>}
                {answer ? (
                  <>
                    <p className={styles.selfGrade}>Удалось определить до подсказки?</p>
                    <div className={styles.gradeGrid}>
                      <button type="button" disabled={loadingAction || pendingGrade === true} onClick={() => grade(false)}><Icon icon={X} size={18} /> Не узнал</button>
                      <button type="button" disabled={loadingAction || pendingGrade === false} onClick={() => grade(true)}><Icon icon={Check} size={18} /> Узнал</button>
                    </div>
                  </>
                ) : (
                  <button type="button" className={styles.primaryButton} disabled={loadingAction} onClick={reveal}>
                    {loadingAction ? "Открываем…" : "Показать ответ"}
                  </button>
                )}
              </div>
            </div>
          </>
        ) : null}
      </div>
    );
  }

  const stats = statsQuery.data;
  const practicalCount = (diagnostic ? [diagnostic] : groups)
    .reduce((sum, group) => sum + group.specimens.filter(item => item.practicalAvailable).length, 0);
  return (
    <div className={["screen", styles.examScreen].join(" ")}>
      {actionError && <p role="alert">{actionError}</p>}
      <button type="button" className={styles.backButton} onClick={() => navigate(back)}>
        <Icon icon={ArrowLeft} size={18} /> {diagnosticTitle ?? "Экзамен"}
      </button>
      {statsQuery.isError && <StateMessage title="Статистика временно недоступна" body="Это ошибка загрузки, а не обнуление данных." onRetry={() => statsQuery.refetch()} />}
      <section className={diagnosticId ? `${styles.hero} ${styles.diagnosticHero}` : styles.hero}>
        <div className={styles.heroTop}>
          <span className={styles.heroIcon}><Icon icon={Microscope} size={24} /></span>
          <span className={styles.heroBadge}>{diagnosticId ? `В раунде ${practicalCount}` : `${practicalCount} препаратов`}</span>
        </div>
        <p className={styles.eyebrow}>{diagnosticTitle ?? "Гистология"}</p>
        <h1>УГАДАЙ ПРЕПАРАТ</h1>
        {!diagnosticId && <div className={styles.statsGrid}>
          <div><strong>{stats?.mastered ?? 0}</strong><span>освоено</span></div>
          <div><strong>{stats?.accuracy ?? 0}%</strong><span>точность</span></div>
          <div><strong>{stats?.activeMistakes ?? 0}</strong><span>ошибок</span></div>
        </div>}
      </section>

      <div className={styles.actions}>
        <button type="button" disabled={loadingAction || practicalCount === 0} onClick={() => startSession("all")}>
          <span><Icon icon={GraduationCap} size={21} /></span>
          <div>
            <strong>{diagnosticId ? "Начать тренировку" : "Практический зачёт"}</strong>
            <small>{diagnosticId ? "Весь перечень этой диагностики" : `10 микрофотографий из ${practicalCount} доступных`}</small>
          </div>
          <Icon icon={ChevronRight} size={18} />
        </button>
        {!diagnosticId && <button type="button" disabled={loadingAction} onClick={() => startSession("mistakes")}>
          <span className={styles.mistakeIcon}><Icon icon={RotateCcw} size={20} /></span>
          <div><strong>Работа над ошибками</strong><small>{stats?.activeMistakes ?? 0} препаратов для повторения</small></div>
          <Icon icon={ChevronRight} size={18} />
        </button>}
      </div>

    </div>
  );
}
