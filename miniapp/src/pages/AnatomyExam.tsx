import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
  checkAnatomyExamAnswer,
  fetchAnatomyExamFlashQuestions,
  fetchAnatomyExamPartQuestions,
  fetchAnatomyExamParts,
  hasContentSession,
} from "../lib/api";
import type { AnatomyExamAnswerResult, AnatomyExamPart, AnatomyExamQuestion } from "../lib/types";
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
    setPhase("menu");
    setRunError(null);
  }, []);
  const handleBack = useCallback(() => {
    if (phase === "menu") navigate("/subjects/anatomy");
    else leaveRun();
  }, [leaveRun, navigate, phase]);
  useTelegramBackButton(handleBack);

  const resetRun = useCallback((nextQuestions: AnatomyExamQuestion[], nextMode: RunMode) => {
    setQuestions(nextQuestions);
    setMode(nextMode);
    setIndex(0);
    setSelectedIndex(null);
    setAnswer(null);
    setCorrectCount(0);
    setMistakes([]);
    setRunError(null);
    setPhase("quiz");
  }, []);

  const startRun = useCallback(async (nextSource: RunSource) => {
    setLoadingRun(true);
    setRunError(null);
    try {
      const nextQuestions = nextSource.kind === "flash"
        ? await fetchAnatomyExamFlashQuestions()
        : await fetchAnatomyExamPartQuestions(nextSource.partId);
      setSource(nextSource);
      resetRun(nextQuestions, "standard");
      hapticSelection();
    } catch (error) {
      console.error("Не удалось загрузить экзаменационный тест", error);
      setRunError("Не удалось загрузить вопросы. Проверь соединение и попробуй ещё раз.");
    } finally {
      setLoadingRun(false);
    }
  }, [resetRun]);

  function startMistakeWork() {
    if (mistakes.length === 0) return;
    const retryQuestions = mistakes.map((item) => item.question);
    resetRun(retryQuestions, "mistakes");
    hapticSelection();
  }

  async function selectAnswer(optionIndex: number) {
    const question = questions[index];
    if (!question || selectedIndex !== null || checking) return;
    setSelectedIndex(optionIndex);
    setChecking(true);
    setRunError(null);
    try {
      const result = await checkAnatomyExamAnswer(question.num, optionIndex);
      setAnswer(result);
      if (result.correct) {
        setCorrectCount((value) => value + 1);
        hapticImpact("light");
      } else {
        setMistakes((items) => [...items, { question }]);
        hapticImpact("heavy");
      }
    } catch (error) {
      console.error("Не удалось проверить ответ", error);
      setSelectedIndex(null);
      setRunError("Ответ не проверен. Нажми вариант ещё раз.");
      hapticImpact("heavy");
    } finally {
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
      <AnatomyExamMenu
        parts={partsQuery.data}
        loading={loadingRun}
        error={runError}
        onStart={startRun}
      />
    );
  }

  if (phase === "result") {
    const percent = questions.length ? Math.round((correctCount / questions.length) * 100) : 0;
    const feedback = resultFeedback(percent);
    return (
      <div className="screen">
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
          <button type="button" className={styles.primaryButton} onClick={startMistakeWork}>
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
              disabled={selectedIndex !== null || checking}
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
}: {
  parts: AnatomyExamPart[];
  loading: boolean;
  error: string | null;
  onStart: (source: RunSource) => void;
}) {
  const total = parts.reduce((sum, part) => sum + part.questionCount, 0);
  return (
    <div className="screen">
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
