import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, CSSProperties } from "react";
import DOMPurify from "dompurify";
import {
  AlertTriangle,
  BookOpen,
  Brain,
  Camera,
  Check,
  CheckCircle2,
  Clipboard,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Type,
  X,
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { fetchSubscriptionSummary, solveAiTask } from "../lib/api";
import { ApiError } from "../lib/apiClient";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { mockSubjects } from "../lib/mockData";
import { Icon } from "../components/Icon";
import styles from "./Ai.module.css";

type Mode = "photo" | "text";

interface SolveResult {
  html: string;
  lowConfidence: boolean;
  note: string | null;
}

const TEXT_SUGGESTIONS = [
  { label: "Объяснить тему", value: "Объясни подробно и понятно: " },
  { label: "Ответ у доски", value: "Подготовь структурированный ответ у доски по теме: " },
  { label: "Решить задачу", value: "Реши задачу пошагово с объяснением: " },
];

const THINKING_STAGES = [
  "Изучаю формулировку",
  "Сверяюсь с материалами ВМедА",
  "Собираю полный ответ",
  "Проверяю структуру и термины",
];

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

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return "Сессия истекла — закрой мини-приложение и открой его заново из бота.";
    return err.message || "Не удалось получить ответ от AI.";
  }
  return "Не удалось получить ответ от AI. Проверь соединение и попробуй ещё раз.";
}

export function AiPage() {
  useTelegramBackButton(null);

  const [searchParams] = useSearchParams();
  const initialMode: Mode = searchParams.get("mode") === "photo" ? "photo" : "text";
  const requestedSubjectId = searchParams.get("subject");
  const availableSubjects = useMemo(() => mockSubjects.filter((subject) => !subject.locked), []);
  const initialSubjectId = availableSubjects.find((subject) => subject.id === requestedSubjectId)?.id
    ?? availableSubjects[0]?.id
    ?? "";

  const [subjectId, setSubjectId] = useState(initialSubjectId);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [text, setText] = useState("");
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreviewUrl, setPhotoPreviewUrl] = useState<string | null>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingStage, setThinkingStage] = useState(0);
  const [result, setResult] = useState<SolveResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestsLeft, setRequestsLeft] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeSubjectRef = useRef<HTMLButtonElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLElement>(null);

  const activeSubject = availableSubjects.find((subject) => subject.id === subjectId) ?? availableSubjects[0];
  const subjectStyle = activeSubject
    ? ({ "--subject-accent": `var(--subject-${activeSubject.accent})` } as CSSProperties)
    : undefined;

  useEffect(() => {
    activeSubjectRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [subjectId]);

  useEffect(() => {
    let cancelled = false;
    fetchSubscriptionSummary()
      .then((status) => {
        if (!cancelled) setRequestsLeft(status.aiRequestsLeft);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl);
    };
  }, [photoPreviewUrl]);

  useEffect(() => {
    if (!isThinking) {
      setThinkingStage(0);
      return;
    }
    const timer = window.setInterval(() => {
      setThinkingStage((current) => Math.min(current + 1, THINKING_STAGES.length - 1));
    }, 2100);
    return () => window.clearInterval(timer);
  }, [isThinking]);

  useEffect(() => {
    if (!result) return;
    requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }, [result]);

  const canSubmit = mode === "text" ? text.trim().length > 0 : photoFile !== null;

  function resetOutcome() {
    setResult(null);
    setError(null);
    setCopied(false);
  }

  function selectMode(nextMode: Mode) {
    setMode(nextMode);
    resetOutcome();
    hapticImpact("light");
  }

  function handlePickPhoto() {
    fileInputRef.current?.click();
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
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
    resetOutcome();
  }

  function handleNewQuestion() {
    setText("");
    handleClearPhoto();
    resetOutcome();
    requestAnimationFrame(() => {
      window.scrollTo({ top: 0, behavior: "smooth" });
      if (mode === "text") textAreaRef.current?.focus();
    });
  }

  async function handleCopyAnswer(safeHtml: string) {
    const plainText = new DOMParser().parseFromString(safeHtml, "text/html").body.textContent ?? "";
    try {
      await navigator.clipboard.writeText(plainText);
      setCopied(true);
      hapticImpact("light");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
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
    ? DOMPurify.sanitize(result.html, { ALLOWED_TAGS: ["b", "strong", "i", "em", "br"], ALLOWED_ATTR: [] })
    : "";

  return (
    <div className={["screen", styles.aiScreen].join(" ")} style={subjectStyle}>
      <section className={styles.hero} aria-labelledby="ai-title">
        <div className={styles.heroGlow} aria-hidden="true" />
        <div className={styles.heroTop}>
          <div className={styles.brandLockup}>
            <span className={styles.brandIcon}><Icon icon={Brain} size={23} /></span>
            <div>
              <span className={styles.heroEyebrow}>VMEDA AI</span>
              <small><i /> учебный ассистент</small>
            </div>
          </div>
          <span className={styles.quotaPill}>
            <Icon icon={Sparkles} size={13} />
            {requestsLeft === null ? "AI доступен" : `${requestsLeft} запросов`}
          </span>
        </div>

        <div className={styles.heroCopy}>
          <h1 id="ai-title">Сложная тема.<br /><span>Понятный разбор.</span></h1>
          <p>Задай вопрос — получишь полный ответ в формате, удобном для подготовки и ответа у доски.</p>
        </div>

        <div className={styles.trustRow} aria-label="Преимущества VMEDA AI">
          <span><Icon icon={BookOpen} size={14} /> Материалы ВМедА</span>
          <span><Icon icon={ShieldCheck} size={14} /> Проверка полноты</span>
        </div>
      </section>

      <section className={styles.composer} aria-label="Новый запрос к VMEDA AI">
        <div className={styles.composerHeader}>
          <div>
            <span className={styles.stepDot}>1</span>
            <div><strong>Выбери предмет</strong><small>AI подстроит структуру и терминологию</small></div>
          </div>
        </div>

        <div className={styles.subjectRail}>
          <div className={styles.subjectRow} role="tablist" aria-label="Предмет">
            {availableSubjects.map((subject) => (
              <button
                key={subject.id}
                ref={subject.id === subjectId ? activeSubjectRef : undefined}
                type="button"
                role="tab"
                aria-selected={subject.id === subjectId}
                className={[styles.subjectChip, subject.id === subjectId ? styles.subjectChipActive : ""].join(" ")}
                style={{ "--chip-accent": `var(--subject-${subject.accent})` } as CSSProperties}
                onClick={() => {
                  setSubjectId(subject.id);
                  resetOutcome();
                  hapticImpact("light");
                }}
              >
                <span>{subject.title.slice(0, 1)}</span>
                {subject.title}
                {subject.id === subjectId && <Icon icon={Check} size={14} />}
              </button>
            ))}
          </div>
        </div>

        <div className={styles.composerDivider} />

        <div className={styles.inputHeading}>
          <div>
            <span className={styles.stepDot}>2</span>
            <div><strong>Добавь задание</strong><small>{activeSubject?.title ?? "Выбранный предмет"}</small></div>
          </div>
          <div className={styles.modeRow}>
            <button
              type="button"
              aria-pressed={mode === "text"}
              className={mode === "text" ? styles.modeButtonActive : ""}
              onClick={() => selectMode("text")}
            >
              <Icon icon={Type} size={15} /> Текст
            </button>
            <button
              type="button"
              aria-pressed={mode === "photo"}
              className={mode === "photo" ? styles.modeButtonActive : ""}
              onClick={() => selectMode("photo")}
            >
              <Icon icon={Camera} size={15} /> Фото
            </button>
          </div>
        </div>

        {mode === "photo" ? (
          <>
            <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={handleFileChange} />
            {photoPreviewUrl ? (
              <div className={styles.photoPreviewWrap}>
                <img src={photoPreviewUrl} alt="Прикреплённое фото задания" className={styles.photoPreview} />
                <div className={styles.photoReady}><Icon icon={CheckCircle2} size={15} /> Фото готово к разбору</div>
                <button type="button" className={styles.photoClear} onClick={handleClearPhoto} aria-label="Убрать фото">
                  <Icon icon={X} size={17} />
                </button>
              </div>
            ) : (
              <button type="button" className={styles.dropZone} onClick={handlePickPhoto}>
                <span className={styles.dropIcon}><Icon icon={Camera} size={25} /></span>
                <span><strong>Добавить фотографию</strong><small>Сделай снимок или выбери из галереи</small></span>
              </button>
            )}
          </>
        ) : (
          <div className={styles.textComposer}>
            <label className="visually-hidden" htmlFor="ai-task-text">Текст задания</label>
            <textarea
              ref={textAreaRef}
              id="ai-task-text"
              className={styles.textArea}
              placeholder="Например: шейное сплетение — образование, топография и ветви. Подробно, с терминами на латыни…"
              value={text}
              maxLength={4000}
              onChange={(event) => {
                setText(event.target.value);
                resetOutcome();
              }}
            />
            <div className={styles.textMeta}>
              <span>{text.length.toLocaleString("ru-RU")} / 4 000</span>
              {text && <button type="button" onClick={() => { setText(""); resetOutcome(); }}>Очистить</button>}
            </div>
          </div>
        )}

        {mode === "text" && !text && (
          <div className={styles.suggestions} aria-label="Шаблоны запроса">
            {TEXT_SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion.label}
                type="button"
                onClick={() => {
                  setText(suggestion.value);
                  resetOutcome();
                  requestAnimationFrame(() => textAreaRef.current?.focus());
                }}
              >
                <Icon icon={Sparkles} size={13} /> {suggestion.label}
              </button>
            ))}
          </div>
        )}

        <button type="button" className={styles.submit} disabled={!canSubmit || isThinking} onClick={handleSubmit}>
          <span><Icon icon={Sparkles} size={19} /></span>
          <strong>{isThinking ? "Готовлю ответ…" : "Разобрать задание"}</strong>
          <small>{isThinking ? "Это может занять несколько секунд" : "Подробно и по существу"}</small>
        </button>
      </section>

      {isThinking && (
        <section className={styles.thinkingCard} aria-live="polite" aria-label="VMEDA AI анализирует задание">
          <div className={styles.thinkingOrb}><Icon icon={Brain} size={23} /></div>
          <div className={styles.thinkingCopy}>
            <span>VMEDA AI работает</span>
            <strong>{THINKING_STAGES[thinkingStage]}</strong>
            <div className={styles.progressTrack}><i style={{ width: `${25 + thinkingStage * 24}%` }} /></div>
          </div>
        </section>
      )}

      {error && (
        <section className={styles.errorCard} role="alert">
          <span className={styles.errorIcon}><Icon icon={AlertTriangle} size={19} /></span>
          <div><strong>Не удалось выполнить запрос</strong><p>{error}</p></div>
          <button type="button" onClick={handleSubmit} disabled={!canSubmit}><Icon icon={RefreshCw} size={16} /> Повторить</button>
        </section>
      )}

      {result && (
        <section ref={resultRef} className={styles.resultCard} aria-labelledby="ai-answer-title">
          <div className={styles.resultAccent} />
          <header className={styles.resultHeader}>
            <div className={styles.resultIdentity}>
              <span><Icon icon={Sparkles} size={19} /></span>
              <div><small>ГОТОВЫЙ РАЗБОР</small><strong id="ai-answer-title">Ответ VMEDA AI</strong></div>
            </div>
            <span className={styles.resultSubject}>{activeSubject?.title ?? "Предмет"}</span>
          </header>

          <div className={styles.answerBody} dangerouslySetInnerHTML={{ __html: safeAnswerHtml }} />

          {result.note && (
            <div className={styles.confidenceNote}>
              <Icon icon={AlertTriangle} size={17} />
              <span>{result.note}</span>
            </div>
          )}

          <footer className={styles.resultFooter}>
            <div className={styles.sourceNote}><Icon icon={ShieldCheck} size={15} /> Материалы ВМедА в приоритете</div>
            <div className={styles.resultActions}>
              <button type="button" onClick={() => handleCopyAnswer(safeAnswerHtml)}>
                <Icon icon={copied ? Check : Clipboard} size={16} /> {copied ? "Скопировано" : "Копировать"}
              </button>
              <button type="button" className={styles.newQuestion} onClick={handleNewQuestion}>
                <Icon icon={RefreshCw} size={16} /> Новый вопрос
              </button>
            </div>
          </footer>
        </section>
      )}
    </div>
  );
}
