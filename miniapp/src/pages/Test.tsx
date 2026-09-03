import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchTestQuestions } from "../lib/api";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { ProgressBar } from "../components/ProgressBar";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Test.module.css";

export function TestPage() {
  const { subjectId = "" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(`/subjects/${subjectId}`));

  const questionsQuery = useQuery({
    queryKey: ["test-questions", subjectId],
    queryFn: () => fetchTestQuestions(subjectId),
  });

  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [correctCount, setCorrectCount] = useState(0);
  const [finished, setFinished] = useState(false);

  if (questionsQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={8} radius="4px" />
        <Skeleton height={80} radius="16px" />
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} height={48} radius="16px" />
        ))}
      </div>
    );
  }

  if (questionsQuery.isError || !questionsQuery.data || questionsQuery.data.length === 0) {
    return (
      <div className="screen">
        <StateMessage title="Тест недоступен" onRetry={() => questionsQuery.refetch()} />
      </div>
    );
  }

  const questions = questionsQuery.data;

  if (finished) {
    const percent = Math.round((correctCount / questions.length) * 100);
    return (
      <div className="screen">
        <Card className={styles.result}>
          <span className={styles.resultScore}>{percent}%</span>
          <span>
            Правильно {correctCount} из {questions.length}
          </span>
          <button
            type="button"
            className={styles.cta}
            onClick={() => navigate(`/subjects/${subjectId}`)}
          >
            К предмету
          </button>
        </Card>
      </div>
    );
  }

  const question = questions[index];

  function handleSelect(optionIndex: number) {
    if (selected !== null) return;
    setSelected(optionIndex);
    const isCorrect = optionIndex === question.correctIndex;
    hapticImpact(isCorrect ? "light" : "heavy");
    if (isCorrect) setCorrectCount((c) => c + 1);
  }

  function handleNext() {
    if (index + 1 >= questions.length) {
      setFinished(true);
      return;
    }
    setIndex((i) => i + 1);
    setSelected(null);
  }

  return (
    <div className="screen">
      <span className={styles.progressLabel}>
        Вопрос {index + 1} из {questions.length}
      </span>
      <ProgressBar percent={((index + (selected !== null ? 1 : 0)) / questions.length) * 100} />

      <p className={styles.question}>{question.question}</p>

      <div className={styles.options} role="radiogroup" aria-label="Варианты ответа">
        {question.options.map((option, optionIndex) => {
          const isSelected = selected === optionIndex;
          const isCorrectOption = optionIndex === question.correctIndex;
          const showState = selected !== null;
          const cls = [
            styles.option,
            showState && isCorrectOption ? styles.optionCorrect : "",
            showState && isSelected && !isCorrectOption ? styles.optionWrong : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={optionIndex}
              type="button"
              className={cls}
              role="radio"
              aria-checked={isSelected}
              onClick={() => handleSelect(optionIndex)}
            >
              {option}
            </button>
          );
        })}
      </div>

      {selected !== null && (
        <button type="button" className={styles.cta} onClick={handleNext}>
          {index + 1 >= questions.length ? "Результаты" : "Дальше"}
        </button>
      )}
    </div>
  );
}
