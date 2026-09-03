import { create } from "zustand";
import type { CourseId } from "./types";
import type { AuthProfile } from "./apiClient";

// Zustand — только для локального состояния интерфейса (§4 ТЗ), не для пользовательских
// данных: прогресс/подписка/избранное живут на сервере и приходят через TanStack Query
// (сейчас — через lib/mockData.ts/lib/apiClient.ts), а не через этот store.

interface UiState {
  selectedCourse: CourseId;
  setSelectedCourse: (course: CourseId) => void;
}

export const useUiStore = create<UiState>((set) => ({
  selectedCourse: 1,
  setSelectedCourse: (course) => set({ selectedCourse: course }),
}));

// Результат ОДНОГО реального события за всю сессию — обмена initData на session-токен при
// старте приложения (см. main.tsx) — сам по себе не пользовательские данные (те приходят через
// TanStack Query, см. lib/api.ts), а состояние "прошла ли аутентификация в этом запуске
// приложения", которое нужно синхронно читать из нескольких мест (TopBar, lib/api.ts::fetchMe).
type AuthStatus = "pending" | "authenticated" | "unavailable" | "failed";

interface AuthState {
  status: AuthStatus;
  profile: AuthProfile | null;
  setAuthenticated: (profile: AuthProfile) => void;
  setUnavailable: () => void;
  setFailed: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: "pending",
  profile: null,
  setAuthenticated: (profile) => set({ status: "authenticated", profile }),
  setUnavailable: () => set({ status: "unavailable", profile: null }),
  setFailed: () => set({ status: "failed", profile: null }),
}));
