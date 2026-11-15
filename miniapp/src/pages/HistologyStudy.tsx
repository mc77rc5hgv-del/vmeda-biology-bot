import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import {
  answerHistologyTest,
  fetchHistologyTestCatalog,
  fetchHistologyTestQuestion,
  fetchHistologyTheory,
  fetchHistologyTheoryAnswer,
  startHistologyTest,
  type HistologyTestAnswer,
  type HistologyTestQuestion,
} from "../lib/apiClient";
import { useTelegramBackButton } from "../lib/telegram";
import styles from "./HistologyExam.module.css";

const examPath = "/histology/exam";
const theoryPath = `${examPath}/theory`;
const testPath = `${examPath}/tests`;
const letters = ["А", "Б", "В", "Г"];

function BackLink({ to, children }: { to: string; children: string }) {
  return <Link className={styles.backButton} to={to}><Icon icon={ArrowLeft} size={18} /> {children}</Link>;
}

export function HistologyTheoryPage() {
  const navigate = useNavigate();
  const { number } = useParams();
  const back = number ? theoryPath : examPath;
  const list = useQuery({ queryKey: ["histology-theory"], queryFn: fetchHistologyTheory, enabled: !number });
  const answer = useQuery({
    queryKey: ["histology-theory", number],
    queryFn: () => fetchHistologyTheoryAnswer(number!),
    enabled: Boolean(number),
  });
  useTelegramBackButton(() => navigate(back));

  return (
    <div className={`screen ${styles.examScreen}`}>
      <BackLink to={back}>{number ? "Теоретические вопросы" : "Экзамен"}</BackLink>
      {number ? (
        answer.isPending ? <Skeleton height={220} />
          : answer.isError ? <StateMessage title="Не удалось открыть вопрос" onRetry={() => answer.refetch()} />
          : (
            <article className={styles.studyAnswer} key={answer.data.number}>
              <h1>{answer.data.number}. {answer.data.title}</h1>
              {answer.data.paragraphs.map((p, index) => <p key={index}><strong>{p.label}</strong> {p.text}</p>)}
            </article>
          )
      ) : (
        <>
          <h1>Теоретические вопросы</h1>
          {list.isPending ? <Skeleton height={210} />
            : list.isError ? <StateMessage title="Не удалось загрузить вопросы" onRetry={() => list.refetch()} />
            : list.data.map((section) => (
              <details key={section.id} className={styles.studyGroup}>
                <summary>{section.title} <span>{section.questions.length}</span></summary>
                {section.questions.map((q) => (
                  <Link key={q.number} to={`${theoryPath}/${q.number}`}>{q.number}. {q.title}</Link>
                ))}
              </details>
            ))}
        </>
      )}
    </div>
  );
}

type SelectedAnswer = { position: number; result: HistologyTestAnswer };
type TestRun = {
  items: HistologyTestQuestion[];
  moduleId: string | null;
  index: number;
  answers: Record<number, SelectedAnswer>;
};

function TestQuestionCard({ question, storedAnswer, onAnswer }: {
  question: HistologyTestQuestion;
  storedAnswer?: SelectedAnswer;
  onAnswer?: (answer: SelectedAnswer) => void;
}) {
  const answer = useMutation({
    mutationFn: (option: number) => answerHistologyTest(question.id, option),
    onSuccess: (result, position) => onAnswer?.({ position, result }),
  });
  const result = storedAnswer?.result ?? answer.data;
  const selection = storedAnswer?.position ?? answer.variables;

  return (
    <article className={styles.studyAnswer}>
      <h2>{question.question}</h2>
      <div className={styles.testOptions}>
        {question.options.map((option, index) => {
          const position = index + 1;
          const correct = result?.correct_option === position;
          const wrong = result?.correct === false && selection === position;
          return (
            <button
              type="button" key={position}
              aria-pressed={selection === position}
              data-verdict={correct ? "correct" : wrong ? "wrong" : undefined}
              disabled={answer.isPending || Boolean(result)}
              onClick={() => answer.mutate(position)}
            >
              <strong>{letters[index]}.</strong> {option}
            </button>
          );
        })}
      </div>
      {answer.isError && <StateMessage title="Не удалось проверить ответ. Попробуй ещё раз." />}
      {result && (
        <div className={styles.testFeedback} aria-live="polite">
          <p><strong>{result.correct === null ? "Спорное задание · без балла" : result.correct ? "Верно" : "Неверно"}</strong></p>
          {result.correct_option && <p>Учебный ответ — {letters[result.correct_option - 1]}.</p>}
          {result.source_correct_option !== result.correct_option && (
            <p>Ключ в сборнике — {letters[result.source_correct_option - 1]}.</p>
          )}
          <p>{result.explanation}</p>
        </div>
      )}
    </article>
  );
}

export function HistologyTestPage() {
  const navigate = useNavigate();
  const { questionId } = useParams();
  const [run, setRun] = useState<TestRun | null>(null);
  const [moduleId, setModuleId] = useState("");
  const catalog = useQuery({
    queryKey: ["histology-test-catalog"], queryFn: fetchHistologyTestCatalog, enabled: !questionId,
  });
  const question = useQuery({
    queryKey: ["histology-test", questionId],
    queryFn: () => fetchHistologyTestQuestion(questionId!),
    enabled: Boolean(questionId),
  });
  const start = useMutation({
    mutationFn: startHistologyTest,
    onSuccess: (items, id) => {
      setRun({ items, moduleId: id, index: 0, answers: {} });
      window.scrollTo({ top: 0, behavior: "instant" });
    },
  });
  const back = questionId ? testPath : examPath;
  useTelegramBackButton(() => run ? setRun(null) : navigate(back));

  const current = run?.items[run.index];
  const topic = catalog.data?.modules.find((module) => module.id === moduleId);

  function move(session: TestRun, offset: number) {
    setRun((previous) => previous === session ? { ...session, index: session.index + offset } : previous);
    window.scrollTo({ top: 0, behavior: "instant" });
  }

  const answered = run ? Object.values(run.answers) : [];
  const scored = answered.filter((answer) => answer.result.correct !== null).length;
  const correct = answered.filter((answer) => answer.result.correct === true).length;
  const grade = run?.moduleId === null && catalog.data?.rules.thresholds.find(
    (band) => correct >= band.min_correct && correct <= band.max_correct,
  );

  return (
    <div className={`screen ${styles.examScreen}`}>
      {run ? (
        <button type="button" className={styles.backButton} onClick={() => setRun(null)}>
          <Icon icon={ArrowLeft} size={18} /> К тестам
        </button>
      ) : <BackLink to={back}>{questionId ? "К тестам" : "Экзамен"}</BackLink>}
      {questionId ? (
        <>
          <h1>Тесты</h1>
          {question.isPending ? <Skeleton height={240} />
            : question.isError ? <StateMessage title="Не удалось загрузить задание" onRetry={() => question.refetch()} />
            : <TestQuestionCard key={question.data.id} question={question.data} />}
        </>
      ) : run ? (
        current ? (
          <>
            <h1 className={styles.testProgress}>Вопрос {run.index + 1} из {run.items.length}</h1>
            <div className={styles.progressTrack} aria-hidden="true">
              <i style={{ width: `${((run.index + 1) / run.items.length) * 100}%` }} />
            </div>
            <TestQuestionCard
              key={current.id}
              question={current}
              storedAnswer={run.answers[run.index]}
              onAnswer={(answer) => setRun((previous) => previous?.items === run.items
                ? { ...previous, answers: { ...previous.answers, [run.index]: answer } }
                : previous)}
            />
            <nav className={styles.testNavigation} aria-label="Переключение вопросов">
              <button type="button" className={styles.testPrevious} disabled={run.index === 0}
                onClick={() => move(run, -1)}>
                <Icon icon={ArrowLeft} size={18} /> Назад
              </button>
              <button type="button" className={styles.primaryButton} disabled={!run.answers[run.index]}
                onClick={() => move(run, 1)}>
                {run.index + 1 === run.items.length ? "Показать результат" : "Следующий вопрос →"}
              </button>
            </nav>
          </>
        ) : (
          <section className={styles.studyAnswer}>
            <h1>Результат теста</h1>
            <p>Верных ответов — <strong>{correct} из {scored}</strong>.</p>
            {grade && <p>Оценка — {grade.grade}.</p>}
            {scored < run.items.length && <p>Спорных заданий без балла — {run.items.length - scored}.</p>}
            <button type="button" className={styles.primaryButton} disabled={start.isPending}
              onClick={() => start.mutate(run.moduleId)}>Пройти ещё раз</button>
          </section>
        )
      ) : (
        <>
          <h1>Тесты</h1>
          {catalog.isPending ? <Skeleton height={210} />
            : catalog.isError ? <StateMessage title="Не удалось загрузить тесты" onRetry={() => catalog.refetch()} />
            : (
              <>
                <button type="button" className={styles.primaryButton} disabled={start.isPending}
                  onClick={() => start.mutate(null)}>
                  {start.isPending && start.variables === null
                    ? "Загружаем…"
                    : `Случайный тест · ${catalog.data.rules.questions_per_attempt} вопросов`}
                </button>
                <section className={styles.studyAnswer}>
                  <label className={styles.studyFilter}>
                    Тесты по темам
                    <select value={moduleId} onChange={(event) => setModuleId(event.target.value)}>
                      <option value="">Выбери тему</option>
                      {catalog.data.modules.map((module) => (
                        <option key={module.id} value={module.id}>{module.title}</option>
                      ))}
                    </select>
                  </label>
                  {topic && (
                    <button type="button" className={styles.primaryButton} disabled={start.isPending}
                      onClick={() => start.mutate(topic.id)}>
                      {start.isPending && start.variables === topic.id
                        ? "Загружаем…" : `Начать тест · вопросов: ${topic.question_count}`}
                    </button>
                  )}
                </section>
              </>
            )}
        </>
      )}
      {start.isError && (
        <StateMessage title="Не удалось начать тест" onRetry={() => start.mutate(start.variables ?? null)} />
      )}
    </div>
  );
}
