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
  viewportStableHeight: number;
  isExpanded: boolean;
  platform: string;
  ready: () => void;
  expand: () => void;
  close: () => void;
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

export function initTelegramApp(): void {
  if (!webApp) return;
  webApp.ready();
  webApp.expand();
  applyThemeAttribute();
  syncViewportHeight();
  webApp.onEvent("themeChanged", applyThemeAttribute);
  webApp.onEvent("viewportChanged", syncViewportHeight);
}

function applyThemeAttribute(): void {
  if (!webApp) return;
  document.documentElement.setAttribute("data-theme", webApp.colorScheme);
  // Telegram заливает область ВНЕ нашего DOM (шапка клиента, и — что важнее для бага "чёрная
  // область под нижней панелью" — любой временной зазор между высотой, на которую страница
  // успела отрисоваться, и высотой, до которой expand() растягивает сам WebView) своим фоном по
  // умолчанию (часто чёрным в тёмной теме), а не фоном страницы. Явно сообщаем Telegram цвет фона
  // экрана (читаем уже применённое значение --background, а не дублируем hex из tokens.css —
  // см. пункт CLAUDE.md про дублирование значений), чтобы даже кратковременный зазор был не
  // "дырой", а тем же фоном, что и сам экран.
  const bg = getComputedStyle(document.documentElement).getPropertyValue("--background").trim();
  if (bg) {
    webApp.setBackgroundColor?.(bg);
    webApp.setHeaderColor?.(bg);
  }
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
