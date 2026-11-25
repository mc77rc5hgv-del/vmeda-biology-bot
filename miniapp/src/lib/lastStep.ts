import { create } from "zustand";
import type { ContinueItem } from "./types";
import { subjectMeta } from "./subjectRegistry";

export function stepFromPath(path: string): ContinueItem | null {
  const match = path.match(/^\/(subjects|materials|tests)\/([\w-]+)(?:\/[^?#]*)?$/);
  const diagnosticGuess = path.match(/^\/histology\/diagnostics\/diagnostika_([1-5])\/guess$/);
  const histology = path.match(/^\/histology\/(diagnostics|specimens\/[^/?#]+|exam(?:\/(?:specimens|guess|tests(?:\/[^/?#]+)?|theory(?:\/\d+)?))?)$/);
  const subjectId = match?.[2] ?? (histology || diagnosticGuess ? "histology" : "");
  const meta = subjectMeta(subjectId);
  if (!meta) return null;
  // /tests/<предмет> — экран-прототип; у подключённых предметов он перенаправляет на предмет.
  if (match?.[1] === "tests" && meta.realBacked && subjectId !== "anatomy") return null;
  const subjectTitle = meta.title;
  const sectionTitle = path === "/histology/exam" ? "Экзамен"
    : path === "/histology/diagnostics" ? "Диагностики"
    : path === "/histology/exam/specimens" ? "Препараты"
    : path === "/histology/exam/guess" ? "Угадай препарат"
    : diagnosticGuess ? `Угадай препарат · Диагностика №${diagnosticGuess[1]}`
    : path.startsWith("/histology/exam/theory") ? "Теоретические вопросы"
    : path.startsWith("/histology/exam/tests") ? "Тесты"
    : path.startsWith("/histology/specimens/") ? "Препарат"
    : match?.[1] === "tests" ? "Тестирование"
    : match?.[1] === "materials" ? "Учебный материал"
    : path.includes("/sections/") ? "Учебный раздел" : "Подготовка по предмету";
  return { path, subjectId, subjectTitle, sectionTitle,
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
        const step = typeof saved?.path === "string" ? stepFromPath(saved.path) : null;
        previous = step ? {...step, updatedAt: saved.updatedAt} : null;
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
