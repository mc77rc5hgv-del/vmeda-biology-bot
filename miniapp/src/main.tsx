import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { authenticateWithTelegram } from "./lib/apiClient";
import { useAuthStore } from "./lib/store";
import { getRawInitData, initTelegramApp, isInsideTelegram } from "./lib/telegram";
import "./styles/global.css";

// HashRouter, не BrowserRouter — Mini App отдаётся статическим хостингом без серверного
// перенаправления неизвестных путей на index.html; hash-роутинг работает при прямом обновлении
// страницы/глубокой ссылке без отдельной конфигурации сервера.

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** Обмен initData на сессию — ОДИН РАЗ при старте приложения, до первого рендера маршрутов
 * (см. lib/api.ts::fetchMe/fetchSubjects — они читают useAuthStore/session-токен и падают
 * обратно на моки, если аутентификация ещё не завершилась или недоступна). Вне Telegram
 * (обычный браузер, локальная разработка) НЕ подделывает initData — это означало бы держать в
 * отгруженном фронтенд-коде способ создать валидную подпись без реального Telegram-клиента, а
 * бэкенд эту подпись всё равно не примет без настоящего секрета бота (см. web_api/auth.py) —
 * приложение просто остаётся на mock-данных, как и весь Этап 2. */
async function authenticateOnBoot(): Promise<void> {
  if (!isInsideTelegram) {
    useAuthStore.getState().setUnavailable();
    return;
  }
  const initData = getRawInitData();
  if (!initData) {
    useAuthStore.getState().setUnavailable();
    return;
  }
  try {
    const profile = await authenticateWithTelegram(initData);
    useAuthStore.getState().setAuthenticated(profile);
  } catch (err) {
    console.warn("authenticateOnBoot: initData verification failed, staying on mock data", err);
    useAuthStore.getState().setUnavailable();
  }
}

function Root() {
  const authStatus = useAuthStore((s) => s.status);

  useEffect(() => {
    initTelegramApp();
    authenticateOnBoot();
  }, []);

  // Короткий сплэш, пока не решится (успехом или нет) один обмен initData -> сессия — без этого
  // главный экран успел бы отрисоваться на mock-данных и через мгновение "моргнуть" на реальные,
  // как только придёт ответ от web_api (см. docstring authenticateOnBoot выше).
  if (authStatus === "pending") {
    return (
      <div style={{ minHeight: "100dvh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--background)" }}>
        <span style={{ fontSize: 13, color: "var(--ink-secondary)" }}>Загрузка…</span>
      </div>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
      </HashRouter>
    </QueryClientProvider>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
