import { useCallback, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronRight,
  CircleAlert,
  RefreshCw,
  Shuffle,
  Target,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  answerAnatomyRun,
  activeAnatomyRun,
  startAnatomyRun,
  fetchAnatomyPreferences,
  setAnatomyPreferences,
  fetchAnatomyRatings,
  fetchAnatomyExamParts,
  hasContentSession,
} from "../lib/api";
import type { AnatomyExamAnswerResult, AnatomyExamPart, AnatomyExamQuestion, AnatomyRun } from "../lib/types";
import { hapticImpact, hapticSelection, useTelegramBackButton } from "../lib/telegram";
import { Card, PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { ProgressBar } from "../components/ProgressBar";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./AnatomyExam.module.css";

type Phase = "menu" | "quiz" | "result";
type RunMode = "standard" | "mistakes";
type RunSource =
  | { kind: "part"; partId: number; title: string }
  | { kind: "flash"; title: string };

interface Mistake {
  question: AnatomyExamQuestion;
}

function resultFeedback(percent: number): { emoji: string; title: string; text: string } {
  if (percent >= 90) return { emoji: "🏅", title: "Отличный результат", text: "Материал усвоен уверенно." };
  if (percent >= 75) return { emoji: "💪", title: "Хорошая работа", text: "Закрепи ошибки — и результат станет ещё выше." };
  if (percent >= 60) return { emoji: "📚", title: "База уже есть", text: "Пройди работу над ошибками и укрепи слабые темы." };
  return { emoji: "🧠", title: "Нужна отработка", text: "Разбери ошибки с пояснениями и повтори попытку." };
}

export function AnatomyExamPage() {
  const navigate = useNavigate();
  const hasSession = hasContentSession();
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const [ratingKind, setRatingKind] = useState<"part" | "flash" | null>(null);
  const preferencesQuery = useQuery({queryKey: ['anatomy-preferences'], queryFn: fetchAnatomyPreferences, enabled: hasSession});
  const preferencesMutation = useMutation({mutationFn: setAnatomyPreferences, onSuccess: (data) => queryClient.setQueryData(['anatomy-preferences'], data)});
  const rating = preferencesQuery.data?.rating ?? false;
  const ratingsQuery = useQuery({queryKey: ['anatomy-ratings', ratingKind], queryFn: () => fetchAnatomyRatings(ratingKind!), enabled: hasSession && ratingKind !== null});
  const requestBusy = useRef(false);
  const [retryOption, setRetryOption] = useState<number | null>(null);
  const activeQuery = useQuery({queryKey: ['anatomy-active'], queryFn: activeAnatomyRun, enabled: hasSession});
  const [phase, setPhase] = useState<Phase>("menu");
  const [mode, setMode] = useState<RunMode>("standard");
  const [source, setSource] = useState<RunSource | null>(null);
  const [questions, setQuestions] = useState<AnatomyExamQuestion[]>([]);
  const [index, setIndex] = useState(0);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [answer, setAnswer] = useState<AnatomyExamAnswerResult | null>(null);
  const [correctCount, setCorrectCount] = useState(0);
  const [mistakes, setMistakes] = useState<Mistake[]>([]);
  const [loadingRun, setLoadingRun] = useState(false);
  const [checking, setChecking] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const partsQuery = useQuery({
    queryKey: ["anatomy-exam-parts"],
    queryFn: fetchAnatomyExamParts,
    enabled: hasSession,
  });

  const leaveRun = useCallback(() => {
    if (requestBusy.current) return;
    setPhase("menu");
    setRunError(null);
    void queryClient.invalidateQueries({queryKey: ['anatomy-active']});
  }, [queryClient]);
  const handleBack = useCallback(() => {
    if (phase === "menu") navigate("/subjects/anatomy");
    else leaveRun();
  }, [leaveRun, navigate, phase]);
  useTelegramBackButton(handleBack);

  const applyRun = useCallback((run: AnatomyRun) => {
    setRetryOption(null);
    setRunId(run.id);
    setQuestions(run.questions);
    setMode(run.kind === "mistakes" ? "mistakes" : "standard");
    setIndex(run.answered);
    setSelectedIndex(null);
    setAnswer(null);
    setCorrectCount(run.correct);
    setMistakes(run.answers.filter((item) => !item.correct).map((item) => ({question: run.questions[item.position]})));
    setRunError(null);
    setPhase(run.finished_at ? "result" : "quiz");
  }, []);

  const startRun = useCallback(async (nextSource: RunSource) => {
    if (requestBusy.current) return;
    requestBusy.current = true;
    setLoadingRun(true);
    setRunError(null);
    try {
      const run = await startAnatomyRun(nextSource.kind, nextSource.kind === "part" ? nextSource.partId : undefined, rating);
      setSource(nextSource);
      applyRun(run);
      hapticSelection();
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Не удалось загрузить вопросы. Повтори попытку.");
    } finally {
      requestBusy.current = false;
      setLoadingRun(false);
    }
  }, [applyRun, rating]);

  async function startMistakeWork() {
    if (requestBusy.current) return;
    requestBusy.current = true;
    setLoadingRun(true);
    try {
      applyRun(await startAnatomyRun("mistakes"));
      hapticSelection();
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Не удалось загрузить ошибки.");
    } finally {
      requestBusy.current = false;
      setLoadingRun(false);
    }
  }

  async function selectAnswer(optionIndex: number) {
    const question = questions[index];
    if (!question || !runId || selectedIndex !== null || requestBusy.current || (retryOption !== null && retryOption !== optionIndex)) return;
    requestBusy.current = true;
    setSelectedIndex(optionIndex);
    setChecking(true);
    setRunError(null);
    try {
      const result = await answerAnatomyRun(runId!, index, optionIndex);
      setRetryOption(null);
      setAnswer(result);
      for (const key of ['anatomy-active', 'anatomy-ratings', 'learning', 'dashboard']) void queryClient.invalidateQueries({queryKey: [key]});
      if (result.correct) {
        setCorrectCount((value) => value + 1);
        hapticImpact("light");
      } else {
        setMistakes((items) => [...items, { question }]);
        hapticImpact("heavy");
      }
    } catch (error) {
      console.error("Не удалось проверить ответ", error);
      setRetryOption(optionIndex);
      setSelectedIndex(null);
      setRunError("Ответ не получен. Повтори тот же вариант — результат сохранится один раз.");
      hapticImpact("heavy");
    } finally {
      requestBusy.current = false;
      setChecking(false);
    }
  }

  function nextQuestion() {
    if (!answer) return;
    if (index + 1 >= questions.length) {
      setPhase("result");
      return;
    }
    setIndex((value) => value + 1);
    setSelectedIndex(null);
    setAnswer(null);
    setRunError(null);
  }

  if (!hasSession) {
    return (
      <div className="screen">
        <StateMessage
          icon={BookOpenCheck}
          title="Открой тест из Telegram"
          body="Экзаменационный банк защищён сессией бота. Вернись в VMEDA и открой Mini App из меню."
          onRetry={() => navigate("/subjects/anatomy")}
          actionLabel="К анатомии"
        />
      </div>
    );
  }

  if (phase === "menu") {
    if (partsQuery.isLoading) {
      return (
        <div className="screen">
          <Skeleton height={180} radius="22px" />
          {Array.from({ length: 5 }).map((_, item) => <Skeleton key={item} height={86} radius="16px" />)}
        </div>
      );
    }
    if (partsQuery.isError || !partsQuery.data) {
      return (
        <div className="screen">
          <StateMessage title="Тесты не загрузились" body="Проверь соединение с интернетом." onRetry={() => partsQuery.refetch()} />
        </div>
      );
    }
    return (
      <div className="screen">
        <AnatomyExamMenu parts={partsQuery.data} loading={loadingRun} error={runError} onStart={startRun}>
          {activeQuery.isError && <StateMessage title="Не удалось проверить сохранённую попытку" onRetry={() => activeQuery.refetch()} />}
          {activeQuery.data && <button type="button" className={styles.primaryButton} onClick={() => {setSource(null); applyRun(activeQuery.data!);}}>Продолжить · {activeQuery.data.answered} из {activeQuery.data.questions.length}</button>}
          <Card className={styles.settingsCard}>
            <label className={styles.switchRow}>
              <input type="checkbox" role="switch" aria-label="Участвовать в рейтинге" checked={rating} disabled={!preferencesQuery.data || preferencesMutation.isPending} onChange={(event) => preferencesMutation.mutate(event.target.checked)} />
              <span className={styles.switchTrack} aria-hidden="true"><span /></span>
              <span><strong>Участвовать в рейтинге</strong><small>Завершённые части учитываются в общем рейтинге</small></span>
            </label>
            {(preferencesQuery.isError || preferencesMutation.isError) && <StateMessage title="Не удалось сохранить режим рейтинга" onRetry={() => preferencesQuery.refetch()} />}
            <div className={styles.ratingTabs} aria-label="Общие рейтинги">
              <button type="button" aria-pressed={ratingKind === 'part'} className={ratingKind === 'part' ? styles.ratingTabActive : undefined} onClick={() => setRatingKind(ratingKind === 'part' ? null : 'part')}>Рейтинг частей</button>
              <button type="button" aria-pressed={ratingKind === 'flash'} className={ratingKind === 'flash' ? styles.ratingTabActive : undefined} onClick={() => setRatingKind(ratingKind === 'flash' ? null : 'flash')}>Рейтинг флэш-теста</button>
            </div>
            {ratingKind && <section className={styles.ranking}>
              <h2>{ratingKind === 'part' ? 'Рейтинг частей' : 'Рейтинг флэш-теста'}</h2>
              {ratingsQuery.isLoading && <Skeleton height={60} />}
              {ratingsQuery.isError && <StateMessage title="Рейтинг временно недоступен" onRetry={() => ratingsQuery.refetch()} />}
              {ratingsQuery.data && <>
                <p>{ratingsQuery.data.own_rank ? `Твоё место: ${ratingsQuery.data.own_rank}` : 'Заверши тест, чтобы попасть в рейтинг.'}</p>
                <ol>{ratingsQuery.data.entries.map((entry) => <li key={entry.rank}>
                  <span className={styles.rankNumber}>{entry.rank}</span>
                  <div><strong>{entry.name}</strong><small>{entry.correct ?? entry.best_correct} из {entry.total ?? entry.best_total} · попыток: {entry.attempts}</small></div>
                </li>)}</ol>
              </>}
            </section>}
          </Card>
          <button type="button" className={styles.secondaryButton} disabled={loadingRun} onClick={startMistakeWork}><Icon icon={Target} size={18} />Повторить сохранённые ошибки</button>
        </AnatomyExamMenu>
      </div>
    );
  }

  if (phase === "result") {
    const percent = questions.length ? Math.round((correctCount / questions.length) * 100) : 0;
    const feedback = resultFeedback(percent);
    return (
      <div className="screen">
        {runError && <p role="alert">{runError}</p>}
        <Card className={styles.resultCard}>
          <div className={styles.scoreRing} style={{ "--score": `${percent * 3.6}deg` } as React.CSSProperties}>
            <span>{percent}%</span>
          </div>
          <div className={styles.resultHeading}>
            <span aria-hidden="true">{feedback.emoji}</span>
            <div>
              <h1>{mode === "mistakes" && mistakes.length === 0 ? "Все ошибки исправлены" : feedback.title}</h1>
              <p>{mode === "mistakes" && mistakes.length === 0 ? "Отлично: повторная попытка пройдена без ошибок." : feedback.text}</p>
            </div>
          </div>
          <div className={styles.resultStats}>
            <div><strong>{questions.length}</strong><span>вопросов</span></div>
            <div><strong className={styles.successText}>{correctCount}</strong><span>верно</span></div>
            <div><strong className={mistakes.length ? styles.dangerText : ""}>{mistakes.length}</strong><span>ошибок</span></div>
          </div>
        </Card>

        {mistakes.length > 0 && (
          <button type="button" className={styles.primaryButton} disabled={loadingRun} onClick={startMistakeWork}>
            <Icon icon={Target} size={18} />
            Работа над ошибками · {mistakes.length}
          </button>
        )}
        {source && (
          <button type="button" className={styles.secondaryButton} onClick={() => startRun(source)} disabled={loadingRun}>
            <Icon icon={RefreshCw} size={17} />
            {loadingRun ? "Загружаем…" : "Пройти тест заново"}
          </button>
        )}
        <button type="button" className={styles.textButton} onClick={leaveRun}>Выбрать другую часть</button>
        {runError && <p className={styles.errorText}>{runError}</p>}
      </div>
    );
  }

  const question = questions[index];
  if (!question) {
    return <div className="screen"><StateMessage title="Вопросы не найдены" onRetry={leaveRun} actionLabel="К списку тестов" /></div>;
  }
  const answered = index + (answer ? 1 : 0);
  const wrongCount = answered - correctCount;

  return (
    <div className={["screen", styles.quizScreen].join(" ")}>
      <div className={styles.quizTop}>
        <div className={styles.quizMeta}>
          <span>{mode === "mistakes" ? "Работа над ошибками" : source?.title}</span>
          <strong>{index + 1} / {questions.length}</strong>
        </div>
        <ProgressBar percent={(answered / questions.length) * 100} color="var(--academic-blue)" label="Прогресс теста" />
        <div className={styles.liveStats}>
          <span><i className={styles.successDot} />Верно {correctCount}</span>
          <span><i className={styles.dangerDot} />Ошибок {wrongCount}</span>
          <span>№{question.num} в банке</span>
        </div>
      </div>

      <Card className={styles.questionCard}>
        <span className={styles.questionEyebrow}>Выбери один правильный ответ</span>
        <h1>{question.question}</h1>
      </Card>

      <div className={styles.options} role="radiogroup" aria-label="Варианты ответа">
        {question.options.map((option, optionIndex) => {
          const isSelected = selectedIndex === optionIndex;
          const isCorrect = answer?.correctIndex === optionIndex;
          const isWrong = Boolean(answer && isSelected && !answer.correct);
          const className = [
            styles.option,
            isCorrect ? styles.optionCorrect : "",
            isWrong ? styles.optionWrong : "",
            selectedIndex !== null && !isSelected && !isCorrect ? styles.optionMuted : "",
          ].filter(Boolean).join(" ");
          return (
            <button
              key={question.optionLetters[optionIndex] ?? optionIndex}
              type="button"
              className={className}
              role="radio"
              aria-checked={isSelected}
              disabled={selectedIndex !== null || checking || (retryOption !== null && retryOption !== optionIndex)}
              onClick={() => selectAnswer(optionIndex)}
            >
              <span className={styles.optionLetter}>{question.optionLetters[optionIndex]?.toUpperCase()}</span>
              <span>{option}</span>
              {isCorrect && <Icon icon={Check} size={18} />}
              {isWrong && <Icon icon={CircleAlert} size={18} />}
            </button>
          );
        })}
      </div>

      {checking && <p className={styles.checkingText}>Проверяем ответ…</p>}
      {runError && <p className={styles.errorText}>{runError}</p>}
      {answer && (
        <div className={[styles.answerPanel, answer.correct ? styles.answerCorrect : styles.answerWrong].join(" ")}>
          <strong>{answer.correct ? "Верно" : `Правильный ответ: ${answer.correctLetter.toUpperCase()}. ${answer.correctText}`}</strong>
          {mode === "mistakes" && !answer.correct && (
            <div className={styles.explanation}>
              <span><Icon icon={BookOpenCheck} size={16} /> Пояснение по Гайворонскому</span>
              <p>{answer.explanation}</p>
            </div>
          )}
        </div>
      )}
      {answer && (
        <button type="button" className={styles.primaryButton} onClick={nextQuestion}>
          {index + 1 >= questions.length ? "Показать результат" : "Следующий вопрос"}
          <Icon icon={ArrowRight} size={18} />
        </button>
      )}
    </div>
  );
}

function AnatomyExamMenu({
  parts,
  loading,
  error,
  onStart,
  children,
}: {
  parts: AnatomyExamPart[];
  loading: boolean;
  error: string | null;
  onStart: (source: RunSource) => void;
  children?: ReactNode;
}) {
  const total = parts.reduce((sum, part) => sum + part.questionCount, 0);
  return (
    <div className={styles.menuContent}>
      <section className={styles.hero}>
        <div className={styles.heroIcon}><Icon icon={BookOpenCheck} size={22} /></div>
        <span className={styles.heroOverline}>Экзаменационная подготовка</span>
        <h1>Тесты по анатомии</h1>
        <p>Проверенные ответы, пояснения по Гайворонскому и отдельная работа над ошибками.</p>
        <div className={styles.metrics}>
          <div><strong>{total.toLocaleString("ru-RU")}</strong><span>вопросов</span></div>
          <div><strong>{parts.length}</strong><span>частей</span></div>
          <div><strong>50</strong><span>флеш-тест</span></div>
        </div>
      </section>

      {children}
      <PressableCard
        className={styles.flashCard}
        aria-label="Начать флеш-тест на 50 случайных вопросов"
        onClick={() => !loading && onStart({ kind: "flash", title: "Флеш-тест · 50 вопросов" })}
      >
        <span className={styles.flashIcon}><Icon icon={Shuffle} size={20} /></span>
        <div><strong>Флеш-тест</strong><span>50 случайных вопросов со всего банка</span></div>
        <Icon icon={ChevronRight} size={18} />
      </PressableCard>

      <div className={styles.sectionHeading}>
        <div><h2>Выбери часть</h2><p>Прогресс считается отдельно за попытку</p></div>
        {loading && <span>Загрузка…</span>}
      </div>
      {error && <p className={styles.errorText}>{error}</p>}
      <div className={styles.partsList}>
        {parts.map((part) => (
          <PressableCard
            key={part.id}
            className={styles.partCard}
            onClick={() => !loading && onStart({ kind: "part", partId: part.id, title: part.title })}
          >
            <span className={styles.partNumber}>{part.id}</span>
            <div className={styles.partContent}>
              <strong>{part.title}</strong>
              <span>{part.topics}</span>
              <small>{part.questionCount} вопросов</small>
            </div>
            <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
          </PressableCard>
        ))}
      </div>
    </div>
  );
}
