import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ChevronRight, Search, X } from "lucide-react";
import { searchMaterials } from "../lib/api";
import { hapticSelection, openTelegramLink, useTelegramBackButton } from "../lib/telegram";
import { useAuthStore } from "../lib/store";
import { PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { SubjectTheme } from "../components/SubjectTheme";
import styles from "./Search.module.css";

const MIN_LENGTH = 2;
const MAX_LENGTH = 80;
const DEBOUNCE_MS = 300;

export function SearchPage() {
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate("/"));
  const authenticated = useAuthStore((state) => state.status === "authenticated");
  // Запрос живёт в адресе: «Назад» из материала возвращает к тем же результатам.
  const [params, setParams] = useSearchParams();
  const urlQuery = params.get("q") ?? "";
  const [input, setInput] = useState(urlQuery);
  const [query, setQuery] = useState(urlQuery.trim());
  const [syncedUrlQuery, setSyncedUrlQuery] = useState(urlQuery);
  const inputRef = useRef<HTMLInputElement>(null);
  // Адрес мог смениться снаружи (переход по ссылке, история) — подхватываем его в поле ввода.
  if (urlQuery !== syncedUrlQuery) {
    setSyncedUrlQuery(urlQuery);
    if (urlQuery !== query) {
      setInput(urlQuery);
      setQuery(urlQuery.trim());
    }
  }

  useEffect(() => {
    if (!params.get("q")) inputRef.current?.focus();
  }, [params]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = input.trim();
      setQuery(next);
      setParams(next ? { q: next } : {}, { replace: true });
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [input, setParams]);

  const searchQuery = useQuery({
    queryKey: ["search", query],
    queryFn: ({ signal }) => searchMaterials(query, signal),
    enabled: authenticated && query.length >= MIN_LENGTH,
    staleTime: 60_000,
  });
  const data = searchQuery.data;

  return (
    <div className="screen">
      <header className="page-intro">
        <h1>Поиск</h1>
        <p>Билеты, вопросы и темы всех предметов</p>
      </header>

      <label className={styles.field}>
        <Icon icon={Search} size={18} />
        <input
          ref={inputRef}
          type="search"
          value={input}
          maxLength={MAX_LENGTH}
          enterKeyHint="search"
          onChange={(event) => setInput(event.target.value)}
          placeholder="Например: митоз, закон Ома, плечевая кость"
          aria-label="Найти тему, билет или вопрос"
        />
        {input && (
          <button type="button" aria-label="Очистить поиск" onClick={() => { setInput(""); inputRef.current?.focus(); }}>
            <Icon icon={X} size={18} />
          </button>
        )}
      </label>

      {!authenticated ? (
        <StateMessage
          icon={Search}
          title="Поиск доступен в Telegram"
          body="Открой мини-приложение из бота, чтобы искать по материалам."
          onRetry={() => openTelegramLink("https://t.me/VMEDA_examen_bot")}
          actionLabel="Открыть бота"
        />
      ) : query.length < MIN_LENGTH ? (
        <p className={styles.hint}>Введи хотя бы {MIN_LENGTH} буквы. Поиск идёт по названиям материалов.</p>
      ) : searchQuery.isLoading ? (
        <div className={styles.list}>{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} height={68} radius="16px" />)}</div>
      ) : searchQuery.isError ? (
        <StateMessage title="Не удалось выполнить поиск" body="Проверь соединение и попробуй ещё раз." onRetry={() => searchQuery.refetch()} />
      ) : !data || data.results.length === 0 ? (
        <StateMessage icon={Search} title="Ничего не найдено" body="Попробуй другое слово или часть слова." />
      ) : (
        <>
          <div className={styles.list} role="list" aria-label="Результаты поиска">
            {data.results.map((item) => (
              <SubjectTheme key={`${item.subjectId}/${item.sectionId}/${item.itemId}`} subjectId={item.subjectId}>
                <PressableCard
                  role="listitem"
                  className={styles.result}
                  onClick={() => {
                    hapticSelection();
                    navigate(`/materials/${item.subjectId}/${item.sectionId}/${encodeURIComponent(item.itemId)}`);
                  }}
                >
                  <div className={styles.resultCopy}>
                    <strong>{item.title}</strong>
                    <span>{item.subjectTitle} · {item.sectionTitle}</span>
                  </div>
                  <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
                </PressableCard>
              </SubjectTheme>
            ))}
          </div>
          {data.hasMore && <p className={styles.hint}>Показаны первые {data.results.length} совпадений — уточни запрос.</p>}
        </>
      )}
    </div>
  );
}
