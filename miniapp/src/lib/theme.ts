import { useSyncExternalStore } from "react";

export type ThemePreference = "auto" | "light" | "dark";
const key = "vmeda:theme:v1";
const valid = (value: unknown): value is ThemePreference => value === "auto" || value === "light" || value === "dark";
let preference: ThemePreference = "auto";
try { const saved = localStorage.getItem(key); if (valid(saved)) preference = saved; } catch { /* Storage may be disabled. */ }
const listeners = new Set<() => void>();

export function applyPreferredTheme(): void {
  const app = window.Telegram?.WebApp;
  const effective = preference === "auto" ? app?.colorScheme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : preference;
  document.documentElement.dataset.theme = effective;
  document.documentElement.style.colorScheme = effective;
  const shell = document.querySelector(".app-shell") ?? document.documentElement;
  const computed = getComputedStyle(shell);
  const background = (computed.getPropertyValue("--subject-page") || computed.getPropertyValue("--background")).trim();
  if (background) {
    try { app?.setBackgroundColor?.(background); app?.setHeaderColor?.(background); } catch { /* Older clients may reject custom header colors. */ }
  }
}

export function setThemePreference(value: ThemePreference): void {
  preference = value;
  try { localStorage.setItem(key, value); } catch { /* Keep the choice for this session. */ }
  applyPreferredTheme();
  listeners.forEach(listener => listener());
}

export function initializeTheme(): void {
  applyPreferredTheme();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyPreferredTheme);
  window.addEventListener("storage", event => {
    if (event.key !== key && event.key !== null) return;
    preference = valid(event.newValue) ? event.newValue : "auto";
    applyPreferredTheme();
    listeners.forEach(listener => listener());
  });
}

export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(listener => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, () => preference);
}
