import { useEffect } from "react";

// Тонкая типизированная обёртка над window.Telegram.WebApp (официальный скрипт, см. index.html).
// Никакой сторонней SDK-библиотеки — см. комментарий в index.html о причине.
//
// ВАЖНО (см. ТЗ раздел 5 «Авторизация Telegram»): initData, отдаваемый отсюда, — это СЫРАЯ,
// НЕПРОВЕРЕННАЯ строка. Она годится только чтобы передать её backend'у в заголовке запроса.
// Ни один экран приложения не должен читать initDataUnsafe для решений о правах/тарифе/админстве —
// это дублировало бы правило "не доверять данным от клиента" на стороне самого клиента без всякого
// смысла. Сегодня (Этап 2, тестовые данные) авторизация ещё не подключена — эта обёртка используется
// только для темы/haptics/кнопки "назад".

interface TelegramThemeParams {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: Record<string, unknown>;
  colorScheme: "light" | "dark";
  themeParams: TelegramThemeParams;
  viewportHeight: number;
  isExpanded: boolean;
  platform: string;
  ready: () => void;
  expand: () => void;
  close: () => void;
  onEvent: (event: string, handler: () => void) => void;
  offEvent: (event: string, handler: () => void) => void;
  BackButton: {
    isVisible: boolean;
    show: () => void;
    hide: () => void;
    onClick: (fn: () => void) => void;
    offClick: (fn: () => void) => void;
  };
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

const webApp = typeof window !== "undefined" ? window.Telegram?.WebApp : undefined;

/** true только внутри настоящего Telegram-клиента; false в обычном браузере при разработке. */
export const isInsideTelegram = Boolean(webApp);

export function initTelegramApp(): void {
  if (!webApp) return;
  webApp.ready();
  webApp.expand();
  applyThemeAttribute();
  webApp.onEvent("themeChanged", applyThemeAttribute);
}

function applyThemeAttribute(): void {
  if (!webApp) return;
  document.documentElement.setAttribute("data-theme", webApp.colorScheme);
}

/** Сырая initData-строка для будущего заголовка Authorization на реальном backend'е.
 * Вне Telegram (локальная разработка) — пустая строка, вызывающий код должен сам решать,
 * что делать (см. lib/mockData.ts — Этап 2 работает без сети вообще). */
export function getRawInitData(): string {
  return webApp?.initData ?? "";
}

export function hapticSelection(): void {
  webApp?.HapticFeedback?.selectionChanged();
}

export function hapticImpact(style: "light" | "medium" | "heavy" = "light"): void {
  webApp?.HapticFeedback?.impactOccurred(style);
}

/** Показывает системную кнопку "Назад" Telegram и вызывает onBack при нажатии — используется
 * вместо собственной кнопки "назад" на любом экране глубже главной. Передай null на главном
 * экране, чтобы скрыть кнопку. Настоящий React-хук (useEffect внутри), а не голая функция —
 * управляет подпиской и её очисткой сам, вызывающему компоненту достаточно одной строки. */
export function useTelegramBackButton(onBack: (() => void) | null): void {
  useEffect(() => {
    if (!webApp) return;
    if (!onBack) {
      webApp.BackButton.hide();
      return;
    }
    webApp.BackButton.show();
    webApp.BackButton.onClick(onBack);
    return () => {
      webApp.BackButton.offClick(onBack);
    };
  }, [onBack]);
}
