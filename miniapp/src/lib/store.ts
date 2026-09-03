import { create } from "zustand";
import type { CourseId } from "./types";

// Zustand — только для локального состояния интерфейса (§4 ТЗ), не для пользовательских
// данных: прогресс/подписка/избранное живут на сервере и приходят через TanStack Query
// (сейчас — через lib/mockData.ts), а не через этот store.

interface UiState {
  selectedCourse: CourseId;
  setSelectedCourse: (course: CourseId) => void;
}

export const useUiStore = create<UiState>((set) => ({
  selectedCourse: 1,
  setSelectedCourse: (course) => set({ selectedCourse: course }),
}));
