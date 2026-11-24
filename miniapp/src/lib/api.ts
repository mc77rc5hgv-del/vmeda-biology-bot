// Диспетчер: каждая функция здесь пробует НАСТОЯЩИЙ web_api, если он реально что-то знает про
// запрошенное (см. REAL_BACKED_SUBJECT_IDS ниже), и использует mockData.ts, если
// нет — либо потому что backend не подключён вообще (нет сессии), либо потому что конкретный
// предмет ещё не имеет контент-адаптера на бэкенде (флаг realBacked в lib/subjectRegistry.ts).
// Компоненты про это ветвление не знают — они видят только эти функции.
import * as apiClient from "./apiClient";
import type { AiSolveInput, AiSolveResult } from "./apiClient";
import * as mock from "./mockData";
import { useAuthStore } from "./store";
import { subjectIdsWhere } from "./subjectRegistry";
import type {
  AccessStatus,
  AnatomyExamAnswerResult,
  AnatomyExamPart,
  AnatomyExamQuestion,
  SearchResponse,
  DashboardStats,
  MaterialDetail,
  LearningState,
  SectionContents,
  SubjectDetail,
  SubjectSummary,
  TestQuestion,
  TestSummary,
  UserProfile,
} from "./types";

export { enterSubject, startAnatomyRun, activeAnatomyRun, answerAnatomyRun,
  fetchAnatomyPreferences, setAnatomyPreferences, fetchAnatomyRatings } from "./apiClient";

// Искусственная задержка — чтобы skeleton-состояния (§17 ТЗ) были видны и проверяемы уже на
// тестовых данных, а не только после подключения настоящей сети.
const MOCK_DELAY_MS = 250;

function resolveAfterDelay<T>(value: T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), MOCK_DELAY_MS));
}

// Предметы с настоящим контент-адаптером (web_api/routers/subjects.py). Backend не отдаёт этот
// список отдельным полем, поэтому флаг realBacked в реестре держится синхронно с ним вручную.
const REAL_BACKED_SUBJECT_IDS = new Set(subjectIdsWhere((meta) => meta.realBacked));

export function isRealBackedSubject(subjectId: string): boolean {
  return REAL_BACKED_SUBJECT_IDS.has(subjectId);
}

function hasSession(): boolean {
  const present = apiClient.hasStoredSession();
  if (!present && useAuthStore.getState().status === "authenticated") throw new apiClient.ApiError(401, "Сессия недоступна. Открой приложение заново из бота.");
  return present;
}

/** Экранам глубокого контента нужен честный способ отличить браузерный preview от Telegram-сессии. */
export function hasContentSession(): boolean {
  return hasSession();
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
  return hasSession() ? apiClient.fetchRealDashboard() : resolveAfterDelay(mock.mockDashboard);
}

/** Поиск идёт только по настоящему бэкенду: в превью без Telegram-сессии возвращает null. */
export function searchMaterials(query: string, signal?: AbortSignal): Promise<SearchResponse | null> {
  if (!hasSession()) return Promise.resolve(null);
  return apiClient.searchRealMaterials(query, signal);
}

export async function fetchSubjects(): Promise<SubjectSummary[]> {
  const mockSubjects = mock.mockSubjects.filter((s) => !REAL_BACKED_SUBJECT_IDS.has(s.id));
  if (!hasSession()) return resolveAfterDelay(mock.mockSubjects);
  try {
    const real = await apiClient.fetchRealSubjects();
    // Реальные карточки заменяют собой mock-версии тех же самых предметов (не дублируют) --
    // остальные 6 предметов по-прежнему идут из mockData.ts, пока не появится их
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
  if (!hasSession() || !REAL_BACKED_SUBJECT_IDS.has(subjectId)) return null;
  return apiClient.fetchRealSection(subjectId, sectionId);
}

export async function fetchGroup(subjectId: string, sectionId: string, groupId: string) {
  if (!hasSession()) return null;
  return apiClient.fetchRealGroup(subjectId, sectionId, groupId);
}

export async function fetchMaterial(
  subjectId: string,
  sectionId: string,
  materialId: string
): Promise<MaterialDetail | null> {
  if (REAL_BACKED_SUBJECT_IDS.has(subjectId) && !hasSession()) return null;
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

/** Тестовые уроки (MaterialDetail.quiz) существуют только у реального контента (см.
 * web_api/content.py) -- эта функция вызывается только когда material.quiz реально есть, что уже
 * подразумевает hasSession() && REAL_BACKED_SUBJECT_IDS, поэтому здесь нет mock-ветки. */
export function checkQuizAnswer(
  subjectId: string,
  sectionId: string,
  itemId: string,
  selectedIndex: number,
  attemptId?: string
) {
  return apiClient.checkQuizAnswer(subjectId, sectionId, itemId, selectedIndex, attemptId);
}

export function fetchTestSummary(subjectId: string): Promise<TestSummary> {
  return resolveAfterDelay(mock.getTestSummary(subjectId));
}

export function fetchTestQuestions(subjectId: string): Promise<TestQuestion[]> {
  return resolveAfterDelay(mock.getTestQuestions(subjectId));
}

export function fetchAnatomyExamParts(): Promise<AnatomyExamPart[]> {
  return apiClient.fetchAnatomyExamParts();
}

export function fetchAnatomyExamPartQuestions(partId: number): Promise<AnatomyExamQuestion[]> {
  return apiClient.fetchAnatomyExamPartQuestions(partId);
}

export function fetchAnatomyExamFlashQuestions(): Promise<AnatomyExamQuestion[]> {
  return apiClient.fetchAnatomyExamFlashQuestions();
}

export function checkAnatomyExamAnswer(
  questionNum: number,
  selectedIndex: number,
): Promise<AnatomyExamAnswerResult> {
  return apiClient.checkAnatomyExamAnswer(questionNum, selectedIndex);
}

export async function fetchAccessStatus(subjectId: string): Promise<AccessStatus> {
  if (!hasSession()) return resolveAfterDelay(mock.getAccessStatus(subjectId));
  return apiClient.fetchRealAccessStatus(subjectId);
}

export function fetchSubscriptionSummary(): Promise<AccessStatus> {
  return hasSession()
    ? apiClient.fetchRealSubscriptionSummary()
    : resolveAfterDelay(mock.mockSubscriptionSummary);
}

const EMPTY_LEARNING_STATE: LearningState = {
  completedKeys: [], favorites: [], lastMaterial: null, completedBySubject: {},
  completedTotal: 0, quizAttempts: 0, quizCorrect: 0,
};

export function fetchLearningState(): Promise<LearningState> {
  return hasSession() ? apiClient.fetchLearningState() : resolveAfterDelay(EMPTY_LEARNING_STATE);
}

export function touchLearningMaterial(input: apiClient.MaterialTouchInput): Promise<LearningState> {
  return hasSession() ? apiClient.touchLearningMaterial(input) : resolveAfterDelay(EMPTY_LEARNING_STATE);
}

export function setLearningFlag(
  input: Pick<apiClient.MaterialTouchInput, "subjectId" | "sectionId" | "materialId">,
  flag: "completed" | "favorite",
  value: boolean,
): Promise<LearningState> {
  return hasSession() ? apiClient.setLearningFlag(input, flag, value) : resolveAfterDelay(EMPTY_LEARNING_STATE);
}

/** web_api/routers/ai.py — единственный содержательный вызов из lib/api.ts, требующий реальной
 * сессии для чего-то большего, чем чтение уже готового контента: вне Telegram (нет initData —
 * см. docstring web_api/routers/ai.py) настоящий эндпоинт недостижим в принципе, поэтому здесь
 * mock-ветка не искусственное упрощение, а единственный вариант вообще что-то показать. */
export const AI_NEEDS_TELEGRAM = "VMEDA AI работает только в мини-приложении, открытом из бота @VMEDA_examen_bot.";

export function solveAiTask(input: AiSolveInput): Promise<AiSolveResult> {
  // Без проверенной Telegram-сессии никаких демо-ответов: фальшивый «разбор» внутри Telegram
  // выглядит как настоящий ответ AI.
  if (!hasSession()) return Promise.reject(new apiClient.ApiError(403, AI_NEEDS_TELEGRAM));
  return apiClient.solveAiTask(input);
}
