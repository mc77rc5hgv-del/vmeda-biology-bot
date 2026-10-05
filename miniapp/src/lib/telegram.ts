import { useEffect } from "react";
import { applyPreferredTheme } from "./theme";

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

interface TelegramInsets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: Record<string, unknown>;
  colorScheme: "light" | "dark";
  themeParams: TelegramThemeParams;
  viewportHeight: number;
  viewportStableHeight: number;
  isExpanded: boolean;
  isFullscreen?: boolean;
  safeAreaInset?: TelegramInsets;
  contentSafeAreaInset?: TelegramInsets;
  isVersionAtLeast?: (version: string) => boolean;
  requestFullscreen?: () => void;
  platform: string;
  ready: () => void;
  expand: () => void;
  close: () => void;
  openInvoice?: (url: string, callback: (status: "paid" | "cancelled" | "failed" | "pending") => void) => void;
  openTelegramLink?: (url: string) => void;
  openLink?: (url: string) => void;
  setBackgroundColor?: (color: string) => void;
  setHeaderColor?: (color: string) => void;
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

/** Telegram на iOS/Android добавляет initData и параметры темы в URL-фрагмент вида
 * #tgWebAppData=... . HashRouter использует тот же фрагмент как путь и без нормализации
 * ошибочно открывает NotFound вместо главной. SDK Telegram считывает параметры ещё до запуска
 * React и хранит их в WebApp.initData, поэтому после этого служебный hash можно безопасно
 * заменить стартовым маршрутом приложения. Настоящие маршруты #/... не трогаем. */
export function normalizeTelegramLaunchHash(): void {
  if (typeof window === "undefined") return;
  const hash = window.location.hash;
  if (!hash || hash.startsWith("#/")) return;
  const launchParams = new URLSearchParams(hash.slice(1));
  if (!launchParams.has("tgWebAppData") && !launchParams.has("tgWebAppVersion")) return;
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search}#/`,
  );
}

let initialized = false;

export function initTelegramApp(): void {
  if (!webApp) return;
  if (initialized) return;
  initialized = true;
  webApp.ready();
  webApp.expand();
  applyThemeAttribute();
  syncViewportHeight();
  webApp.onEvent("themeChanged", applyThemeAttribute);
  webApp.onEvent("viewportChanged", syncViewportHeight);
  if (webApp.requestFullscreen && (!webApp.isVersionAtLeast || webApp.isVersionAtLeast("8.0"))) {
    webApp.onEvent("safeAreaChanged", syncViewportHeight);
    webApp.onEvent("contentSafeAreaChanged", syncViewportHeight);
    webApp.onEvent("fullscreenChanged", syncViewportHeight);
    webApp.onEvent("fullscreenFailed", () => {
      webApp.expand();
      syncViewportHeight();
    });
    if (!webApp.isFullscreen) {
      try { webApp.requestFullscreen(); }
      catch { webApp.expand(); }
    }
    syncViewportHeight();
  }
}

function applyThemeAttribute(): void {
  applyPreferredTheme();
}

/** Синхронизирует CSS-переменную --tg-viewport-height с реальной высотой WebView Telegram
 * (viewportStableHeight/viewportHeight), а не полагается только на 100vh/100dvh. Проблема: после
 * expand() Telegram раскрывает WebView до полной высоты, но на части клиентов (замечено на
 * некоторых версиях мобильного приложения) браузерный движок не пересчитывает dvh-юниты сам по
 * себе без отдельного события resize/orientationchange — контент застревает отрисованным на
 * ПРЕЖНЕЙ, меньшей высоте, и всё, что ниже (включая нижнюю панель, закреплённую position:fixed),
 * "проваливается" в середину экрана, а под ним видна чистая область WebView. Явная запись
 * пиксельного значения в CSS-переменную из JS форсирует пересчёт layout, в отличие от пассивной
 * переоценки dvh-юнита. Слушаем viewportChanged (а не только вызываем один раз при старте) —
 * событие срабатывает и при повторном раскрытии, и при появлении/скрытии системной клавиатуры. */
function syncViewportHeight(): void {
  if (!webApp) return;
  const height = webApp.viewportStableHeight || webApp.viewportHeight || window.innerHeight;
  if (height > 0) {
    document.documentElement.style.setProperty("--tg-viewport-height", `${height}px`);
  }
  for (const side of ["top", "bottom", "left", "right"] as const) {
    const device = webApp.safeAreaInset?.[side] ?? 0;
    const controls = webApp.contentSafeAreaInset?.[side] ?? 0;
    document.documentElement.style.setProperty(`--vmeda-safe-${side}`, `${Math.max(0, device) + Math.max(0, controls)}px`);
  }
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

/** Открывает Telegram-ссылку нативно внутри Mini App; в обычном браузере использует новую вкладку. */
export function openTelegramLink(url: string): void {
  if (webApp?.openTelegramLink) {
    webApp.openTelegramLink(url);
    return;
  }
  if (webApp?.openLink) {
    webApp.openLink(url);
    return;
  }
  const popup = window.open(url, "_blank", "noopener,noreferrer");
  if (!popup) window.location.assign(url);
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

export function canOpenInvoice(): boolean {
  return Boolean(webApp?.initData && webApp.openInvoice && (!webApp.isVersionAtLeast || webApp.isVersionAtLeast("6.1")));
}
export function openInvoice(url: string, callback: (status: "paid" | "cancelled" | "failed" | "pending") => void): void {
  if (!canOpenInvoice()) throw new Error("Открой miniapp в обновлённом Telegram для оплаты.");
  webApp!.openInvoice!(url, callback);
}
