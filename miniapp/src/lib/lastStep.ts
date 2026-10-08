import { create } from "zustand";
import type { ContinueItem } from "./types";

const titles: Record<string, string> = {
  anatomy: "Анатомия", histology: "Гистология", chemistry: "Химия",
  biology: "Биология", latin: "Латинский язык", law: "Правоведение", physics: "Физика",
  physiology: "Нормальная физиология", operative_surgery: "Оперативная хирургия",
  biochemistry: "Биохимия", pharmacology: "Фармакология",
};

export function stepFromPath(path: string): ContinueItem | null {
  const match = path.match(/^\/(subjects|materials|tests)\/([\w-]+)(?:\/[^?#]*)?$/);
  const subjectId = match?.[2] ?? (path.match(/^\/histology\/(exam|specimens\/[^/?#]+)$/) ? "histology" : "");
  if (!titles[subjectId]) return null;
  const sectionTitle = path === "/histology/exam" ? "Диагностика препаратов"
    : path.startsWith("/histology/specimens/") ? "Препарат"
    : match?.[1] === "tests" ? "Тестирование"
    : match?.[1] === "materials" ? "Учебный материал"
    : path.includes("/sections/") ? "Учебный раздел" : "Подготовка по предмету";
  return { path, subjectId, subjectTitle: titles[subjectId], sectionTitle,
    materialTitle: sectionTitle, order: 0, totalInSection: 0 };
}

function storageKey(owner: string) { return `vmeda:last-step:v1:${owner}`; }

// Только закладка интерфейса. Результаты, доступ и статистика остаются на сервере.
export const useLastStepStore = create<{
  steps: Record<string, ContinueItem | null>;
  remember: (owner: string, path: string) => void;
}>((set, get) => ({
  steps: {},
  remember(owner, path) {
    let previous = get().steps[owner];
    if (previous === undefined) {
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey(owner)) ?? "null");
        previous = typeof saved?.path === "string" ? {...stepFromPath(saved.path)!, updatedAt: saved.updatedAt} : null;
      } catch { previous = null; }
    }
    let next = stepFromPath(path);
    if (next) next.updatedAt = new Date().toISOString();
    // Возврат из занятия к меню того же предмета не должен терять глубокую ссылку.
    if (!next || (path === `/subjects/${next.subjectId}` && previous?.subjectId === next.subjectId)) next = previous;
    if (get().steps[owner]?.path === next?.path && get().steps[owner] !== undefined) return;
    set((state) => ({ steps: { ...state.steps, [owner]: next ?? null } }));
    if (next) {
      try { localStorage.setItem(storageKey(owner), JSON.stringify({ path: next.path, updatedAt: next.updatedAt })); } catch { /* Закладка работает в памяти при закрытом хранилище. */ }
    }
  },
}));
