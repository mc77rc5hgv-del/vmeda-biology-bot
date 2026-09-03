import { useState } from "react";
import { AlertTriangle, Camera, Sparkles, Type } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { mockSubjects } from "../lib/mockData";
import { Card } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import styles from "./Ai.module.css";

type Mode = "photo" | "text";

interface MockAnswer {
  text: string;
  lowConfidence: boolean;
  note: string | null;
}

/** Мок-ответ AI-раздела — иллюстрирует ИМЕННО те состояния, которые ТЗ требует явно показывать
 * пользователю (§11): низкая уверенность, недостаточно данных. Реальный вызов появится вместе
 * с /api/v1/ai/solve и /api/v1/ai/solve-photo (Этап 3+), эта функция — только для верстки. */
function buildMockAnswer(mode: Mode, subjectTitle: string): MockAnswer {
  if (mode === "photo") {
    return {
      text: `По материалам курса «${subjectTitle}»: краткий разбор задания появится здесь после подключения реального AI-пайплайна бота.`,
      lowConfidence: true,
      note: "Фотография частично нечёткая — уверенность в ответе ниже обычной. Попробуй переснять при лучшем освещении.",
    };
  }
  return {
    text: `Краткий ответ по предмету «${subjectTitle}» — заглушка для прототипа. Подробный разбор со ссылками на темы курса появится после подключения ai/service.solve().`,
    lowConfidence: false,
    note: null,
  };
}

export function AiPage() {
  useTelegramBackButton(null); // раздел нижней навигации — своей кнопки "Назад" нет

  const [searchParams] = useSearchParams();
  const initialMode: Mode = searchParams.get("mode") === "photo" ? "photo" : "text";

  const [subjectId, setSubjectId] = useState(mockSubjects[0]?.id ?? "");
  const [mode, setMode] = useState<Mode>(initialMode);
  const [text, setText] = useState("");
  const [photoAttached, setPhotoAttached] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [answer, setAnswer] = useState<MockAnswer | null>(null);

  const subject = mockSubjects.find((s) => s.id === subjectId);
  const canSubmit = mode === "text" ? text.trim().length > 0 : photoAttached;

  function handleSubmit() {
    if (!canSubmit || !subject) return;
    hapticImpact("light");
    setIsThinking(true);
    setAnswer(null);
    window.setTimeout(() => {
      setAnswer(buildMockAnswer(mode, subject.title));
      setIsThinking(false);
    }, 900);
  }

  return (
    <div className="screen">
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700 }}>VMEDA AI</h1>
        <p style={{ fontSize: 13, color: "var(--ink-secondary)", marginTop: 4 }}>
          Разбор заданий по материалам курса
        </p>
      </div>

      <div className={styles.subjectRow} role="tablist" aria-label="Предмет">
        {mockSubjects
          .filter((s) => !s.locked)
          .map((s) => (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={s.id === subjectId}
              className={[styles.subjectChip, s.id === subjectId ? styles.subjectChipActive : ""].join(" ")}
              onClick={() => setSubjectId(s.id)}
            >
              {s.title}
            </button>
          ))}
      </div>

      <div className={styles.modeRow}>
        <button
          type="button"
          className={[styles.modeButton, mode === "photo" ? styles.modeButtonActive : ""].join(" ")}
          onClick={() => setMode("photo")}
        >
          <Icon icon={Camera} size={16} />
          Фото
        </button>
        <button
          type="button"
          className={[styles.modeButton, mode === "text" ? styles.modeButtonActive : ""].join(" ")}
          onClick={() => setMode("text")}
        >
          <Icon icon={Type} size={16} />
          Текст
        </button>
      </div>

      {mode === "photo" ? (
        <button
          type="button"
          className={styles.dropZone}
          onClick={() => setPhotoAttached(true)}
          aria-pressed={photoAttached}
        >
          <Icon icon={Camera} size={28} />
          <span>{photoAttached ? "Фото прикреплено — можно отправлять" : "Открыть камеру или выбрать фото"}</span>
        </button>
      ) : (
        <textarea
          className={styles.textArea}
          placeholder="Опиши задание или вставь вопрос текстом…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      )}

      <button type="button" className={styles.submit} disabled={!canSubmit} onClick={handleSubmit}>
        Разобрать задание
      </button>

      {isThinking && (
        <Card>
          <Skeleton height={14} width="40%" />
          <div style={{ height: 8 }} />
          <Skeleton height={60} />
        </Card>
      )}

      {answer && (
        <Card style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Icon icon={Sparkles} size={16} color="var(--academic-blue)" />
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--academic-blue)" }}>Ответ VMEDA AI</span>
          </div>
          <p className={styles.answerBody}>{answer.text}</p>
          {answer.note && (
            <div className={styles.confidenceNote}>
              <Icon icon={AlertTriangle} size={16} />
              <span>{answer.note}</span>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
