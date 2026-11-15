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

function TestQuestionCard({ question, onNext }: {
  question: HistologyTestQuestion;
  onNext?: (answer: HistologyTestAnswer) => void;
}) {
  const [selection, setSelection] = useState<number | null>(null);
  const answer = useMutation({
    mutationFn: (option: number) => answerHistologyTest(question.id, option),
  });
  const result = answer.data;

  return (
    <article className={styles.studyAnswer}>
      <h2>№{question.number}. {question.question}</h2>
      <div className={styles.testOptions}>
        {question.options.map((option, index) => {
          const position = index + 1;
          return (
            <button
              type="button" key={position}
              aria-pressed={selection === position}
              disabled={answer.isPending || Boolean(result)}
              onClick={() => { setSelection(position); answer.mutate(position); }}
            >
              <strong>{letters[index]}.</strong> {option}
            </button>
          );
        })}
      </div>
      {answer.isError && <StateMessage title="Не удалось проверить ответ. Попробуй ещё раз." />}
      {result && (
        <div className={styles.testFeedback} aria-live="polite">
          <p><strong>{result.correct === null ? "Спорное задание" : result.correct ? "Верно" : "Неверно"}</strong></p>
          {result.correct_option && <p>Учебный ответ — {letters[result.correct_option - 1]}.</p>}
          {result.source_correct_option !== result.correct_option && (
            <p>Ключ в сборнике — {letters[result.source_correct_option - 1]}.</p>
          )}
          <p>{result.explanation}</p>
          {onNext && <button type="button" className={styles.primaryButton} onClick={() => onNext(result)}>Дальше</button>}
        </div>
      )}
    </article>
  );
}

export function HistologyTestPage() {
  const navigate = useNavigate();
  const { questionId } = useParams();
  const [run, setRun] = useState<{ items: HistologyTestQuestion[]; index: number; correct: number } | null>(null);
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
    onSuccess: (items) => setRun({ items, index: 0, correct: 0 }),
  });
  const back = questionId ? testPath : examPath;
  useTelegramBackButton(() => run ? setRun(null) : navigate(back));

  return (
    <div className={`screen ${styles.examScreen}`}>
      {run ? (
        <button type="button" className={styles.backButton} onClick={() => setRun(null)}>
          <Icon icon={ArrowLeft} size={18} /> К тестам
        </button>
      ) : <BackLink to={back}>{questionId ? "К тестам" : "Экзамен"}</BackLink>}
      <h1>Тесты</h1>
      {questionId ? (
        question.isPending ? <Skeleton height={240} />
          : question.isError ? <StateMessage title="Не удалось загрузить задание" onRetry={() => question.refetch()} />
          : <TestQuestionCard key={question.data.id} question={question.data} />
      ) : run ? (
        run.index < run.items.length ? (
          <>
            <p>Вопрос {run.index + 1} из {run.items.length}</p>
            <TestQuestionCard
              key={run.items[run.index].id}
              question={run.items[run.index]}
              onNext={(answer) => setRun((current) => current === run
                ? { ...current, index: current.index + 1, correct: current.correct + Number(answer.correct) }
                : current)}
            />
          </>
        ) : (
          <section className={styles.studyAnswer}>
            <h2>{run.correct} из {run.items.length}</h2>
            <p>Оценка — {catalog.data?.rules.thresholds.find(
              (grade) => run.correct >= grade.min_correct && run.correct <= grade.max_correct,
            )?.grade}.</p>
            <button type="button" className={styles.primaryButton} disabled={start.isPending}
              onClick={() => start.mutate()}>Пройти ещё раз</button>
          </section>
        )
      ) : catalog.isPending ? <Skeleton height={210} />
        : catalog.isError ? <StateMessage title="Не удалось загрузить тесты" onRetry={() => catalog.refetch()} />
        : (
          <>
            <button type="button" className={styles.primaryButton} disabled={start.isPending}
              onClick={() => start.mutate()}>
              {start.isPending ? "Загружаем…" : `Начать тест · ${catalog.data.rules.questions_per_attempt} вопросов`}
            </button>
            <label className={styles.studyFilter}>
              Банк заданий
              <select value={moduleId} onChange={(event) => setModuleId(event.target.value)}>
                <option value="">Выбери тему</option>
                {catalog.data.modules.map((module) => <option key={module.id} value={module.id}>{module.title}</option>)}
              </select>
            </label>
            {moduleId && (
              <div className={styles.studyGroup}>
                {catalog.data.questions.filter((q) => q.module_id === moduleId).map((q) => (
                  <Link key={q.id} to={`${testPath}/${q.id}`}>{q.number}. {q.question}</Link>
                ))}
              </div>
            )}
          </>
        )}
      {start.isError && <StateMessage title="Не удалось начать тест" onRetry={() => start.mutate()} />}
    </div>
  );
}
