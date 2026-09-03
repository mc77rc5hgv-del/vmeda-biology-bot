// Диспетчер: каждая функция здесь пробует НАСТОЯЩИЙ web_api, если он реально что-то знает про
// запрошенное (см. REAL_BACKED_SUBJECT_IDS ниже), и молча падает обратно на mockData.ts, если
// нет — либо потому что backend не подключён вообще (нет сессии), либо потому что конкретный
// предмет ещё не имеет контент-адаптера на бэкенде (7 из 11 предметов, см. web_api/README.md).
// Компоненты про это ветвление не знают — они видят только эти функции.
import * as apiClient from "./apiClient";
import * as mock from "./mockData";
import { useAuthStore } from "./store";
import type {
  AccessStatus,
  ContinueItem,
  DashboardStats,
  MaterialDetail,
  SectionContents,
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

// См. web_api/content.py -- список предметов, у которых есть настоящий контент-адаптер. Держать
// синхронно с REPO_ROOT/web_api/routers/subjects.py вручную -- backend не отдаёт "список
// подключённых предметов" отдельным полем, а список из четырёх статичен и меняется редко.
const REAL_BACKED_SUBJECT_IDS = new Set(["biochemistry", "pharmacology", "latin", "law"]);

export function isRealBackedSubject(subjectId: string): boolean {
  return REAL_BACKED_SUBJECT_IDS.has(subjectId);
}

function hasSession(): boolean {
  return apiClient.hasStoredSession();
}

export async function fetchMe(): Promise<UserProfile> {
  if (hasSession()) {
    const authProfile = useAuthStore.getState().profile;
    const me = await apiClient.fetchRealMe();
    if (authProfile) return apiClient.mergeProfile(authProfile, me);
    throw new Error("Telegram-профиль отсутствует в текущей сессии");
  }
  return resolveAfterDelay(mock.mockUser);
}

export function fetchDashboard(): Promise<DashboardStats> {
  // Готовность/серия/XP считаются backend'ом по формуле §13 ТЗ -- эндпоинта для них ещё нет
  // (см. web_api/README.md "Что дальше"), поэтому пока всегда mock, вне зависимости от сессии.
  return resolveAfterDelay(mock.mockDashboard);
}

export function fetchContinueItem(): Promise<ContinueItem | null> {
  return resolveAfterDelay(mock.mockContinue);
}

export async function fetchSubjects(): Promise<SubjectSummary[]> {
  const mockSubjects = mock.mockSubjects.filter((s) => !REAL_BACKED_SUBJECT_IDS.has(s.id));
  if (!hasSession()) return resolveAfterDelay(mock.mockSubjects);
  try {
    const real = await apiClient.fetchRealSubjects();
    // Реальные карточки заменяют собой mock-версии тех же самых предметов (не дублируют) --
    // остальные 7 статичных предметов по-прежнему идут из mockData.ts, пока не появится их
    // собственный контент-адаптер.
    return [...real, ...mockSubjects];
  } catch (err) {
    console.error("fetchSubjects: real /api/v1/subjects failed", err);
    throw err;
  }
}

export async function fetchSubjectDetail(subjectId: string): Promise<SubjectDetail | null> {
  if (hasSession() && REAL_BACKED_SUBJECT_IDS.has(subjectId)) {
    try {
      return await apiClient.fetchRealSubjectDetail(subjectId);
    } catch (err) {
      console.error(`fetchSubjectDetail(${subjectId}): real API failed`, err);
      throw err;
    }
  }
  return resolveAfterDelay(mock.getSubjectDetail(subjectId));
}

export async function fetchSection(subjectId: string, sectionId: string): Promise<SectionContents | null> {
  if (!REAL_BACKED_SUBJECT_IDS.has(subjectId)) return null; // mock-предметы: нет списка элементов, см. SectionPage
  return apiClient.fetchRealSection(subjectId, sectionId);
}

export async function fetchGroup(subjectId: string, sectionId: string, groupId: string) {
  return apiClient.fetchRealGroup(subjectId, sectionId, groupId);
}

export async function fetchMaterial(
  subjectId: string,
  sectionId: string,
  materialId: string
): Promise<MaterialDetail | null> {
  if (hasSession() && REAL_BACKED_SUBJECT_IDS.has(subjectId)) {
    try {
      return await apiClient.fetchRealMaterial(subjectId, sectionId, materialId);
    } catch (err) {
      console.error(`fetchMaterial(${subjectId}): real API failed`, err);
      throw err;
    }
  }
  return resolveAfterDelay(mock.getMaterial(subjectId, sectionId, materialId));
}

export function fetchTestSummary(subjectId: string): Promise<TestSummary> {
  return resolveAfterDelay(mock.getTestSummary(subjectId));
}

export function fetchTestQuestions(subjectId: string): Promise<TestQuestion[]> {
  return resolveAfterDelay(mock.getTestQuestions(subjectId));
}

export async function fetchAccessStatus(subjectId: string): Promise<AccessStatus> {
  if (!hasSession()) return resolveAfterDelay(mock.getAccessStatus(subjectId));
  try {
    return await apiClient.fetchRealAccessStatus(subjectId);
  } catch (err) {
    console.error(`fetchAccessStatus(${subjectId}): real API failed`, err);
    return {
      canOpenSubject: false,
      canDownload: false,
      canUseAi: false,
      aiRequestsLeft: null,
      subscriptionExpiresAt: null,
      subscriptionTitle: null,
      lockedReason: "Не удалось безопасно проверить доступ. Повторите попытку.",
    };
  }
}

export function fetchSubscriptionSummary(): Promise<AccessStatus> {
  return hasSession()
    ? apiClient.fetchRealSubscriptionSummary()
    : resolveAfterDelay(mock.mockSubscriptionSummary);
}
