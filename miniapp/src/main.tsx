import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App } from "./App";
import { ApiError, authenticateWithTelegram } from "./lib/apiClient";
import { useAuthStore } from "./lib/store";
import { getRawInitData, initTelegramApp, isInsideTelegram, normalizeTelegramLaunchHash } from "./lib/telegram";
import "./styles/global.css";
import { initializeTheme } from "./lib/theme";

normalizeTelegramLaunchHash();
initializeTheme();

// HashRouter, не BrowserRouter — Mini App отдаётся статическим хостингом без серверного
// перенаправления неизвестных путей на index.html; hash-роутинг работает при прямом обновлении
// страницы/глубокой ссылке без отдельной конфигурации сервера.

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});

/** Обмен initData на сессию — ОДИН РАЗ при старте приложения, до первого рендера маршрутов
 * (см. lib/api.ts::fetchMe/fetchSubjects — они читают useAuthStore/session-токен). Вне Telegram
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
    console.error("authenticateOnBoot: initData verification failed", err);
    // Внутри Telegram нельзя продолжать на демонстрационных данных: это показало бы фиктивный
    // доступ/подписку именно тогда, когда сервер не смог подтвердить личность пользователя.
    const message = err instanceof ApiError && err.status === 403
      ? err.message
      : err instanceof ApiError && err.status === 401
        ? "Сессия истекла. Закройте мини-приложение и откройте его заново из бота VMEDA."
        : "Не удалось связаться с сервером VMEDA. Проверьте интернет и попробуйте снова через минуту.";
    useAuthStore.getState().setFailed(message);
  }
}

export function Root() {
  const authStatus = useAuthStore((s) => s.status);
  const failureMessage = useAuthStore((s) => s.failureMessage);

  useEffect(() => {
    initTelegramApp();
    authenticateOnBoot();
  }, []);

  useEffect(() => {
    if (authStatus !== 'authenticated') return;
    // Purchases and grants in Telegram must be visible without reopening the Mini App.
    const refresh = () => {
      if (document.visibilityState !== 'visible') return;
      for (const key of ['access', 'subscription', 'subscriptions', 'me', 'learning', 'dashboard', 'histology-stats', 'anatomy-active', 'anatomy-ratings', 'anatomy-preferences', 'continue', 'subjects', 'subject', 'section', 'group', 'material']) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
    };
    const timer = window.setInterval(refresh, 15_000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('online', refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
      window.removeEventListener('online', refresh);
    };
  }, [authStatus]);

  // Короткий сплэш, пока не решится (успехом или нет) один обмен initData -> сессия — без этого
  // главный экран успел бы отрисоваться на mock-данных и через мгновение "моргнуть" на реальные,
  // как только придёт ответ от web_api (см. docstring authenticateOnBoot выше).
  if (authStatus === "pending") {
    return (
      <div style={{ minHeight: "var(--tg-viewport-height, 100dvh)", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--background)" }}>
        <span style={{ fontSize: 13, color: "var(--ink-secondary)" }}>Загрузка…</span>
      </div>
    );
  }

  if (authStatus === "failed") {
    return (
      <div style={{ minHeight: "var(--tg-viewport-height, 100dvh)", display: "grid", placeItems: "center", padding: 24, background: "var(--background)" }}>
        <div style={{ maxWidth: 360, textAlign: "center" }}>
          <h1 style={{ fontSize: 20, marginBottom: 8 }}>Не удалось войти</h1>
          <p style={{ fontSize: 14, color: "var(--ink-secondary)", lineHeight: 1.5 }}>
            {failureMessage}
          </p>
          <button type="button" onClick={() => window.location.reload()} style={{ marginTop: 20, padding: "12px 20px", minHeight: 44, borderRadius: 14, border: "1px solid var(--ink-secondary)", background: "var(--background)", color: "var(--ink)", font: "inherit", cursor: "pointer" }}>
            Попробовать снова
          </button>
        </div>
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
