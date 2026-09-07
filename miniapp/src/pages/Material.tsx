import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { Lock } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { checkQuizAnswer, fetchMaterial } from "../lib/api";
import { ApiError, type QuizAnswerResult } from "../lib/apiClient";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { AuthenticatedImage } from "../components/AuthenticatedImage";
import styles from "./Material.module.css";
import testStyles from "./Test.module.css";

export function MaterialPage() {
  const { subjectId = "", sectionId = "", materialId = "1" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(`/subjects/${subjectId}`));

  const materialQuery = useQuery({
    queryKey: ["material", subjectId, sectionId, materialId],
    queryFn: () => fetchMaterial(subjectId, sectionId, materialId),
  });

  // Тестовый урок (material.quiz) -- ответ выбирается на этом же экране, сервер сравнивает его
  // на своей стороне (см. apiClient.checkQuizAnswer/web_api/content.py::check_quiz_answer,
  // correct_index никогда не приходит в GET /materials заранее). Состояние сбрасывается при
  // переходе на другой materialId -- компонент не размонтируется React Router'ом при смене
  // параметра одного и того же маршрута, поэтому сброс идёт прямо во время рендера (React-
  // рекомендуемый паттерн "adjusting state when a prop changes"), а не эффектом.
  const [quizMaterialId, setQuizMaterialId] = useState(materialId);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [answerResult, setAnswerResult] = useState<QuizAnswerResult | null>(null);
  const [answering, setAnswering] = useState(false);
  if (materialId !== quizMaterialId) {
    setQuizMaterialId(materialId);
    setSelectedIndex(null);
    setAnswerResult(null);
    setAnswering(false);
  }

  async function handleSelectOption(optionIndex: number) {
    if (selectedIndex !== null || answering) return;
    setAnswering(true);
    setSelectedIndex(optionIndex);
    try {
      const result = await checkQuizAnswer(subjectId, sectionId, materialId, optionIndex);
      setAnswerResult(result);
      hapticImpact(result.correct ? "light" : "heavy");
    } catch {
      // Не удалось проверить ответ (сеть/сессия) -- откатываем выбор, чтобы можно было
      // попробовать снова, а не застрять с "выбранным, но непроверенным" вариантом.
      setSelectedIndex(null);
    } finally {
      setAnswering(false);
    }
  }

  if (materialQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={24} width="70%" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} height={90} radius="16px" />
        ))}
      </div>
    );
  }

  if (materialQuery.isError || !materialQuery.data) {
    const err = materialQuery.error;
    if (err instanceof ApiError && err.status === 403) {
      // Реально достижимо только прямой навигацией (напр. кнопкой "назад/вперёд" на теме,
      // модуль которой закрылся между открытиями) — обычный путь через GroupPage блокирует
      // такую тему раньше (см. Group.tsx), не давая на неё вообще перейти.
      return (
        <div className="screen">
          <StateMessage icon={Lock} title="Материал закрыт" body={err.message} />
        </div>
      );
    }
    return (
      <div className="screen">
        <StateMessage title="Материал не найден" onRetry={() => materialQuery.refetch()} />
      </div>
    );
  }

  const material = materialQuery.data;
  const safeHtml = DOMPurify.sanitize(material.rawHtml ?? "", {
    ALLOWED_TAGS: ["a", "b", "blockquote", "br", "code", "del", "em", "i", "p", "pre", "s", "strong", "u"],
    ALLOWED_ATTR: ["href", "title"],
  });
  const order = material.order;
  const total = material.totalInSection;
  // Реальный контент (см. lib/apiClient.ts) присылает готовые id соседей — id вида "core_p1_1"
  // не образуют предсказуемую числовую последовательность, в отличие от mock-материалов
  // (lib/mockData.ts), где id == order и "следующий" можно просто прибавлением единицы.
  const isRealContent = material.prevId !== undefined;

  function goTo(nextMaterialId: string) {
    hapticImpact("light");
    navigate(`/materials/${subjectId}/${sectionId}/${nextMaterialId}`);
  }

  function goBackToList() {
    if (material.groupId) {
      navigate(`/subjects/${subjectId}/sections/${sectionId}/groups/${material.groupId}`);
    } else {
      navigate(`/subjects/${subjectId}/sections/${sectionId}`);
    }
  }

  const hasPrev = isRealContent ? material.prevId != null : order > 1;
  const hasNext = isRealContent ? material.nextId != null : order < total;

  function handlePrev() {
    if (isRealContent && material.prevId) goTo(material.prevId);
    else if (!isRealContent) goTo(String(order - 1));
  }

  function handleNext() {
    if (isRealContent) {
      if (material.nextId) goTo(material.nextId);
      else goBackToList();
    } else if (order < total) {
      goTo(String(order + 1));
    } else {
      navigate(`/subjects/${subjectId}`);
    }
  }

  return (
    <div className={`screen ${styles.materialScreen}`}>
      <div className={styles.header}>
        <span className={styles.eyebrow}>
          Тема {order} из {total}
        </span>
        <h1 className={styles.title}>{material.title}</h1>
      </div>

      {isRealContent ? (
        <Card className={styles.block}>
          {/* Импортируемые материалы проходят DOMPurify: Telegram-источник нельзя считать
              вечным доверенным источником только потому, что результат сохранён в JSON. */}
          <div className={styles.blockBody} dangerouslySetInnerHTML={{ __html: safeHtml }} />
        </Card>
      ) : (
        material.blocks.map((block) => (
          <Card key={block.kind} className={styles.block}>
            <span className={styles.blockTitle}>{block.title}</span>
            <p className={styles.blockBody}>{block.body}</p>
          </Card>
        ))
      )}

      {material.quiz && (
        <>
          <div className={testStyles.options} role="radiogroup" aria-label="Варианты ответа">
            {material.quiz.options.map((option, optionIndex) => {
              const isSelected = selectedIndex === optionIndex;
              const isCorrectOption = answerResult && optionIndex === answerResult.correctIndex;
              const showState = answerResult !== null;
              const cls = [
                testStyles.option,
                showState && isCorrectOption ? testStyles.optionCorrect : "",
                showState && isSelected && !isCorrectOption ? testStyles.optionWrong : "",
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
                  disabled={selectedIndex !== null}
                  onClick={() => handleSelectOption(optionIndex)}
                >
                  {option}
                </button>
              );
            })}
          </div>
          {answerResult && (
            <p style={{ fontSize: 14, fontWeight: 600, color: answerResult.correct ? "var(--success)" : "var(--danger)" }}>
              {answerResult.correct ? "✅ Верно!" : "❌ Неверно."}
            </p>
          )}
        </>
      )}

      {material.media && material.media.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {material.media.map((m, i) => (
            <figure key={i} style={{ margin: 0 }}>
              <AuthenticatedImage src={m.url} alt={m.caption || `Иллюстрация ${i + 1}`} className={styles.media} />
              {m.caption && (
                <figcaption style={{ fontSize: 12, color: "var(--ink-secondary)", marginTop: 4 }}>
                  {m.caption}
                </figcaption>
              )}
            </figure>
          ))}
        </div>
      )}

      {material.sources && material.sources.length > 0 && (
        <p style={{ fontSize: 12, color: "var(--ink-secondary)" }}>
          📎 Источники: {material.sources.join(", ")}
        </p>
      )}

      {/* Тестовый урок форсирует ответ: до выбора варианта навигация скрыта (тот же принцип,
          что клавиатура quiz-урока в боте -- см. handlers/dynamic_courses.py::
          get_dynamic_group_quiz_keyboard, без prev/next, пока не нажата одна из кнопок варианта). */}
      {(!material.quiz || answerResult !== null) && (
        <div className={styles.nav}>
          <button
            type="button"
            className={`${styles.navButton} ${styles.navSecondary}`}
            disabled={!hasPrev}
            onClick={handlePrev}
          >
            Назад
          </button>
          <button type="button" className={`${styles.navButton} ${styles.navPrimary}`} onClick={handleNext}>
            {hasNext ? "Понятно, дальше" : "Завершить раздел"}
          </button>
        </div>
      )}
    </div>
  );
}
