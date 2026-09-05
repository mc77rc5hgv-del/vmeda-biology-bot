import { useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { AlertTriangle, Camera, Sparkles, Type, X } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { fetchSubscriptionSummary, solveAiTask } from "../lib/api";
import { ApiError } from "../lib/apiClient";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { mockSubjects } from "../lib/mockData";
import { Card } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import styles from "./Ai.module.css";

type Mode = "photo" | "text";

interface SolveResult {
  html: string;
  lowConfidence: boolean;
  note: string | null;
}

/** dataURL вида "data:image/jpeg;base64,/9j/4AAQ..." -> голый base64 без префикса — ровно то,
 * что ждёт web_api/routers/ai.py (см. AiSolveRequest.image_base64). */
function readFileAsBareBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const commaIndex = result.indexOf(",");
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error("Не удалось прочитать файл"));
    reader.readAsDataURL(file);
  });
}

/** Единая точка перевода ошибки запроса в понятный студенту текст — статусы отражают ровно то,
 * что реально возвращает web_api/routers/ai.py (429 квота/занято, 503 автовыключатель/перегрузка,
 * 422 отказ модели, 400 некорректный запрос), а не общее "что-то пошло не так". */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Сессия истекла — закрой мини-приложение и открой его заново из бота.";
    return err.message || "Не удалось получить ответ от AI.";
  }
  return "Не удалось получить ответ от AI. Проверь соединение и попробуй ещё раз.";
}

export function AiPage() {
  useTelegramBackButton(null); // раздел нижней навигации — своей кнопки "Назад" нет

  const [searchParams] = useSearchParams();
  const initialMode: Mode = searchParams.get("mode") === "photo" ? "photo" : "text";

  const [subjectId, setSubjectId] = useState(mockSubjects[0]?.id ?? "");
  const [mode, setMode] = useState<Mode>(initialMode);
  const [text, setText] = useState("");
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreviewUrl, setPhotoPreviewUrl] = useState<string | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [result, setResult] = useState<SolveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestsLeft, setRequestsLeft] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSubscriptionSummary()
      .then((status) => {
        if (!cancelled) setRequestsLeft(status.aiRequestsLeft);
      })
      .catch(() => {
        // квота — не критичная для экрана информация, тихо остаёмся без неё
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl);
    };
  }, [photoPreviewUrl]);

  const canSubmit = mode === "text" ? text.trim().length > 0 : photoFile !== null;

  function resetOutcome() {
    setResult(null);
    setError(null);
  }

  function handlePickPhoto() {
    fileInputRef.current?.click();
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null;
    if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl);
    setPhotoFile(file);
    setPhotoPreviewUrl(file ? URL.createObjectURL(file) : null);
    resetOutcome();
  }

  function handleClearPhoto() {
    if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl);
    setPhotoFile(null);
    setPhotoPreviewUrl(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleSubmit() {
    if (!canSubmit || isThinking) return;
    hapticImpact("light");
    setIsThinking(true);
    resetOutcome();
    try {
      const imageBase64 = mode === "photo" && photoFile ? await readFileAsBareBase64(photoFile) : undefined;
      const response = await solveAiTask({
        mode,
        text: mode === "text" ? text.trim() : undefined,
        imageBase64,
      });
      setResult({ html: response.answerHtml, lowConfidence: response.lowConfidence, note: response.confidenceNote });
      setRequestsLeft(response.requestsLeft);
      hapticImpact("light");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setIsThinking(false);
    }
  }

  const safeAnswerHtml = result
    ? DOMPurify.sanitize(result.html, { ALLOWED_TAGS: ["b", "i", "br"], ALLOWED_ATTR: [] })
    : "";

  return (
    <div className="screen">
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700 }}>VMEDA AI</h1>
        <p style={{ fontSize: 13, color: "var(--ink-secondary)", marginTop: 4 }}>
          Разбор заданий по материалам курса
          {requestsLeft !== null && ` · осталось запросов сегодня: ${requestsLeft}`}
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
          onClick={() => {
            setMode("photo");
            resetOutcome();
          }}
        >
          <Icon icon={Camera} size={16} />
          Фото
        </button>
        <button
          type="button"
          className={[styles.modeButton, mode === "text" ? styles.modeButtonActive : ""].join(" ")}
          onClick={() => {
            setMode("text");
            resetOutcome();
          }}
        >
          <Icon icon={Type} size={16} />
          Текст
        </button>
      </div>

      {mode === "photo" ? (
        <>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="visually-hidden"
            onChange={handleFileChange}
          />
          {photoPreviewUrl ? (
            <div className={styles.photoPreviewWrap}>
              <img src={photoPreviewUrl} alt="Прикреплённое фото задания" className={styles.photoPreview} />
              <button type="button" className={styles.photoClear} onClick={handleClearPhoto} aria-label="Убрать фото">
                <Icon icon={X} size={16} />
              </button>
            </div>
          ) : (
            <button type="button" className={styles.dropZone} onClick={handlePickPhoto}>
              <Icon icon={Camera} size={28} />
              <span>Открыть камеру или выбрать фото</span>
            </button>
          )}
        </>
      ) : (
        <textarea
          className={styles.textArea}
          placeholder="Опиши задание или вставь вопрос текстом…"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            resetOutcome();
          }}
        />
      )}

      <button type="button" className={styles.submit} disabled={!canSubmit || isThinking} onClick={handleSubmit}>
        {isThinking ? "Разбираю…" : "Разобрать задание"}
      </button>

      {isThinking && (
        <Card>
          <Skeleton height={14} width="40%" />
          <div style={{ height: 8 }} />
          <Skeleton height={60} />
        </Card>
      )}

      {error && (
        <Card style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Icon icon={AlertTriangle} size={16} color="var(--danger)" />
          <span style={{ fontSize: 13, color: "var(--ink)" }}>{error}</span>
        </Card>
      )}

      {result && (
        <Card style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Icon icon={Sparkles} size={16} color="var(--academic-blue)" />
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--academic-blue)" }}>Ответ VMEDA AI</span>
          </div>
          {/* Ответ модели проходит DOMPurify так же, как обычный материал (см. Material.tsx) —
              внешний, не полностью доверенный текст, даже если это наш собственный backend. */}
          <div className={styles.answerBody} dangerouslySetInnerHTML={{ __html: safeAnswerHtml }} />
          {result.note && (
            <div className={styles.confidenceNote}>
              <Icon icon={AlertTriangle} size={16} />
              <span>{result.note}</span>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
