// Единственный файл, который нужно будет переписать на реальные fetch('/api/v1/...') вызовы,
// когда backend (web_api/, Этап 3 ТЗ) будет готов — все страницы уже сегодня ходят только сюда,
// а не в lib/mockData.ts напрямую, так что подключение реального API не потребует трогать компоненты.
import * as mock from "./mockData";
import type {
  AccessStatus,
  ContinueItem,
  DashboardStats,
  MaterialDetail,
  SubjectDetail,
  SubjectSummary,
  TestQuestion,
  TestSummary,
  UserProfile,
} from "./types";

// Искусственная задержка — чтобы skeleton-состояния (§17 ТЗ) были видны и проверяемы уже на
// тестовых данных, а не только после подключения настоящей сети.
const MOCK_DELAY_MS = 250;

function resolveAfterDelay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), MOCK_DELAY_MS));
}

export function fetchMe(): Promise<UserProfile> {
  return resolveAfterDelay(mock.mockUser);
}

export function fetchDashboard(): Promise<DashboardStats> {
  return resolveAfterDelay(mock.mockDashboard);
}

export function fetchContinueItem(): Promise<ContinueItem | null> {
  return resolveAfterDelay(mock.mockContinue);
}

export function fetchSubjects(): Promise<SubjectSummary[]> {
  return resolveAfterDelay(mock.mockSubjects);
}

export function fetchSubjectDetail(subjectId: string): Promise<SubjectDetail | null> {
  return resolveAfterDelay(mock.getSubjectDetail(subjectId));
}

export function fetchMaterial(subjectId: string, sectionId: string, materialId: string): Promise<MaterialDetail | null> {
  return resolveAfterDelay(mock.getMaterial(subjectId, sectionId, materialId));
}

export function fetchTestSummary(subjectId: string): Promise<TestSummary> {
  return resolveAfterDelay(mock.getTestSummary(subjectId));
}

export function fetchTestQuestions(subjectId: string): Promise<TestQuestion[]> {
  return resolveAfterDelay(mock.getTestQuestions(subjectId));
}

export function fetchAccessStatus(subjectId: string): Promise<AccessStatus> {
  return resolveAfterDelay(mock.getAccessStatus(subjectId));
}

export function fetchSubscriptionSummary(): Promise<AccessStatus> {
  return resolveAfterDelay(mock.mockSubscriptionSummary);
}
