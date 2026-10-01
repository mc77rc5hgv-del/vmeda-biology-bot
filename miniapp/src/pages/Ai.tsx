import { useEffect, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { AlertTriangle, Camera, CheckCircle2, Sparkles, Type, X } from "lucide-react";
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

const TEXT_SUGGESTIONS = [
  "Объясни термин: ",
  "Реши задачу пошагово: ",
  "Составь план ответа: ",
];

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
  const requestedSubjectId = searchParams.get("subject");
  const initialSubjectId = mockSubjects.find((subject) => !subject.locked && subject.id === requestedSubjectId)?.id
    ?? mockSubjects.find((subject) => !subject.locked)?.id
    ?? "";

  const [subjectId, setSubjectId] = useState(initialSubjectId);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [text, setText] = useState("");
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreviewUrl, setPhotoPreviewUrl] = useState<string | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [result, setResult] = useState<SolveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestsLeft, setRequestsLeft] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeSubjectRef = useRef<HTMLButtonElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    activeSubjectRef.current?.scrollIntoView({ behavior: "auto", block: "nearest", inline: "center" });
  }, [subjectId]);

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
        subjectId,
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
      <section className={styles.hero}>
        <div className={styles.heroTop}>
          <span className={styles.heroIcon}><Icon icon={Sparkles} size={22} /></span>
          <span className={styles.quotaPill}>
            {requestsLeft === null ? "Учебный помощник" : `${requestsLeft} запросов`}
          </span>
        </div>
        <span className={styles.heroEyebrow}>VMEDA AI</span>
        <h1>Разберём задание вместе</h1>
        <p>Выбери предмет и отправь фото или текст. Ответ будет основан на материалах курса.</p>
      </section>

      <section className={styles.controlSection}>
        <div className={styles.sectionLabel}><span>1</span> Предмет</div>
        <div className={styles.subjectRail}>
          <div className={styles.subjectRow} role="tablist" aria-label="Предмет">
            {mockSubjects
              .filter((s) => !s.locked)
              .map((s) => (
                <button
                  key={s.id}
                  ref={s.id === subjectId ? activeSubjectRef : undefined}
                  type="button"
                  role="tab"
                  aria-selected={s.id === subjectId}
                  className={[styles.subjectChip, s.id === subjectId ? styles.subjectChipActive : ""].join(" ")}
                  onClick={() => {
                    setSubjectId(s.id);
                    resetOutcome();
                  }}
                >
                  {s.title}
                </button>
              ))}
          </div>
        </div>
      </section>

      <section className={styles.controlSection}>
        <div className={styles.sectionLabel}><span>2</span> Формат задания</div>
        <div className={styles.modeRow}>
          <button
            type="button"
            aria-pressed={mode === "photo"}
            className={[styles.modeButton, mode === "photo" ? styles.modeButtonActive : ""].join(" ")}
            onClick={() => {
              setMode("photo");
              resetOutcome();
            }}
          >
            <Icon icon={Camera} size={17} />
            Фото
          </button>
          <button
            type="button"
            aria-pressed={mode === "text"}
            className={[styles.modeButton, mode === "text" ? styles.modeButtonActive : ""].join(" ")}
            onClick={() => {
              setMode("text");
              resetOutcome();
            }}
          >
            <Icon icon={Type} size={17} />
            Текст
          </button>
        </div>
      </section>

      {mode === "photo" ? (
        <>
          {/* Без capture="environment" -- этот атрибут на большинстве мобильных браузеров/WebView
              (в т.ч. внутри Telegram) заставляет input сразу открывать камеру в обход системного
              выбора источника, так что "выбрать фото из галереи" тут было физически недостижимо
              (реальная жалоба пользователя со скриншотом — вместо пикера открывалась только
              камера). Без capture браузер показывает свой обычный диалог выбора файла, который
              на iOS/Android сам предлагает и камеру, и галерею -- ровно то, что уже обещано
              текстом кнопки ниже ("Открыть камеру или выбрать фото"). */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            hidden
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
              <span className={styles.dropIcon}><Icon icon={Camera} size={26} /></span>
              <strong>Добавить фотографию</strong>
              <small>Камера или изображение из галереи</small>
            </button>
          )}
        </>
      ) : (
        <>
          <label className="visually-hidden" htmlFor="ai-task-text">Текст задания</label>
          <div className={styles.textInputWrap}>
            <textarea
              ref={textAreaRef}
              id="ai-task-text"
              className={styles.textArea}
              placeholder="Вставь вопрос или опиши задание…"
              value={text}
              maxLength={4000}
              onChange={(e) => {
                setText(e.target.value);
                resetOutcome();
              }}
            />
            <div className={styles.textMeta}>
              <span>{text.length.toLocaleString("ru-RU")} / 4 000</span>
              {text && (
                <button type="button" onClick={() => { setText(""); resetOutcome(); }}>
                  Очистить
                </button>
              )}
            </div>
          </div>
          {!text && (
            <div className={styles.suggestions} aria-label="Примеры запросов">
              {TEXT_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    setText(suggestion);
                    resetOutcome();
                    requestAnimationFrame(() => textAreaRef.current?.focus());
                  }}
                >
                  {suggestion.trim()}
                </button>
              ))}
            </div>
          )}
        </>
      )}

      <button type="button" className={styles.submit} disabled={!canSubmit || isThinking} onClick={handleSubmit}>
        <Icon icon={Sparkles} size={18} />
        {isThinking ? "Анализирую задание…" : "Разобрать задание"}
      </button>

      {isThinking && (
        <Card>
          <Skeleton height={14} width="40%" />
          <div style={{ height: 8 }} />
          <Skeleton height={60} />
        </Card>
      )}

      {error && (
        <Card className={styles.errorCard}>
          <span className={styles.errorIcon}><Icon icon={AlertTriangle} size={18} /></span>
          <div><strong>Не удалось выполнить запрос</strong><p>{error}</p></div>
        </Card>
      )}

      {result && (
        <Card className={styles.resultCard}>
          <div className={styles.resultHeader}>
            <span><Icon icon={CheckCircle2} size={17} /></span>
            <div><strong>Ответ VMEDA AI</strong><small>Проверяй формулировки перед сдачей</small></div>
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
