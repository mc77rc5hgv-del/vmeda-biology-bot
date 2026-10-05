// Тонкий слой поверх настоящего web_api (см. web_api/README.md в репозитории бота) — единственное
// место, которое знает про формат данных на проводе (snake_case, ровно как в web_api/schemas.py)
// и переводит его в app-типы из lib/types.ts. lib/api.ts (диспетчер, решающий mock vs реальный
// вызов) — единственный, кто это импортирует; компоненты про существование этого файла не знают.
import type {
  AccessStatus,
  AnatomyExamAnswerResult,
  AnatomyExamPart,
  AnatomyExamQuestion,
  AnatomyRun,
  ContentSection,
  DashboardStats,
  HistologyCatalog,
  HistologyPracticalQuestion,
  HistologySpecimen,
  HistologySpecimenSummary,
  HistologyStats,
  MaterialDetail,
  LearningState,
  SectionContents,
  SectionItemRef,
  SubjectDetail,
  SubjectSummary,
  UserProfile,
} from "./types";
import { clearStoredSessionToken, getStoredSessionToken, storeSessionToken } from "./session";
import { useAuthStore } from "./store";

function expireSession() {
  clearStoredSessionToken();
  useAuthStore.getState().setFailed("Сессия истекла. Закрой приложение и открой его заново из бота.");
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

function absoluteApiUrl(path: string): string {
  return path.startsWith("http://") || path.startsWith("https://") ? path : `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getStoredSessionToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init?.body) headers.set("Content-Type", "application/json");

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401) expireSession();
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // тело не JSON — оставляем statusText
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

/** Загружает защищённое медиа с тем же session-токеном, что и JSON API. */
export async function fetchAuthorizedBlob(url: string): Promise<Blob> {
  const token = getStoredSessionToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { headers });
  if (!response.ok) {
    if (response.status === 401) expireSession();
    throw new ApiError(response.status, response.statusText);
  }
  const blob = await response.blob();
  const bytes = new Uint8Array(await blob.arrayBuffer());
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (signature.every((value, index) => bytes[index] === value)) {
    // Some WebViews report load for a damaged PNG but display an empty rectangle.
    const view = new DataView(bytes.buffer);
    let position = 8;
    let ended = false;
    while (position + 12 <= bytes.length) {
      const length = view.getUint32(position);
      const end = position + 12 + length;
      if (end > bytes.length) throw new Error("Повреждённый PNG-файл");
      let crc = 0xffffffff;
      for (let index = position + 4; index < end - 4; index++) {
        crc = (crc >>> 8) ^ PNG_CRC_TABLE[(crc ^ bytes[index]) & 255];
      }
      if ((crc ^ 0xffffffff) >>> 0 !== view.getUint32(end - 4)) throw new Error("Повреждённый PNG-файл");
      ended = bytes[position + 4] === 73 && bytes[position + 5] === 69 && bytes[position + 6] === 78 && bytes[position + 7] === 68;
      position = end;
      if (ended) break;
    }
    if (!ended) throw new Error("Неполный PNG-файл");
  }
  return blob;
}

const PNG_CRC_TABLE = Uint32Array.from({ length: 256 }, (_, value) => {
  let crc = value;
  for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  return crc >>> 0;
});

// ==================== аутентификация (ТЗ §5) ====================

interface TelegramAuthResponseWire {
  session_token: string;
  user_id: number;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
  photo_url: string | null;
}

export interface AuthProfile {
  userId: number;
  firstName: string | null;
  lastName: string | null;
  username: string | null;
  photoUrl: string | null;
}

/** Единственное место, где сырая initData вообще куда-то отправляется — прямиком на backend для
 * проверки подписи (см. web_api/auth.py). Сохраняет session-токен для всех последующих запросов
 * и возвращает профиль, который Telegram только что подтвердил живым (см. schemas.py:
 * TelegramAuthResponse — эти поля свежее, чем всё, что успел записать бот при последнем /start). */
export async function authenticateWithTelegram(initData: string): Promise<AuthProfile> {
  const body: TelegramAuthResponseWire = await apiFetch("/api/v1/auth/telegram", {
    method: "POST",
    body: JSON.stringify({ init_data: initData }),
  });
  storeSessionToken(body.session_token);
  return {
    userId: body.user_id,
    firstName: body.first_name,
    lastName: body.last_name,
    username: body.username,
    photoUrl: body.photo_url,
  };
}

export function hasStoredSession(): boolean {
  return getStoredSessionToken() !== null;
}

// ==================== /me ====================

interface MeResponseWire {
  user_id: number;
  first_name: string | null;
  username: string | null;
  referral_count: number;
  referral_count_this_month: number;
  has_free_access: boolean;
  has_active_subscription: boolean;
  subscription_tier_title: string | null;
  is_admin: boolean;
}

export interface RealMe {
  userId: number;
  firstName: string | null;
  username: string | null;
  referralCount: number;
  referralCountThisMonth: number;
  hasFreeAccess: boolean;
  hasActiveSubscription: boolean;
  subscriptionTierTitle: string | null;
  isAdmin: boolean;
}

export async function fetchRealMe(): Promise<RealMe> {
  const body: MeResponseWire = await apiFetch("/api/v1/me");
  return {
    userId: body.user_id,
    firstName: body.first_name,
    username: body.username,
    referralCount: body.referral_count,
    referralCountThisMonth: body.referral_count_this_month,
    hasFreeAccess: body.has_free_access,
    hasActiveSubscription: body.has_active_subscription,
    subscriptionTierTitle: body.subscription_tier_title,
    isAdmin: body.is_admin,
  };
}

interface DashboardStatsWire {
  streak_days: number;
  xp: number;
  readiness_percent: number;
  daily_goal_minutes: number;
  minutes_left_today: number;
}

export async function fetchRealDashboard(): Promise<DashboardStats> {
  const body: DashboardStatsWire = await apiFetch("/api/v1/learning/dashboard");
  return {
    streakDays: body.streak_days,
    xp: body.xp,
    readinessPercent: body.readiness_percent,
    dailyGoalMinutes: body.daily_goal_minutes,
    minutesLeftToday: body.minutes_left_today,
  };
}

// ==================== подписка и доступ ====================

interface AccessStatusWire {
  trial_available?: boolean;
  can_open_subject: boolean;
  can_download: boolean;
  can_use_ai: boolean;
  ai_requests_left: number | null;
  subscription_expires_at: string | null;
  subscription_title: string | null;
  locked_reason: string | null;
}

function toAccessStatus(wire: AccessStatusWire): AccessStatus {
  return {
    canOpenSubject: wire.can_open_subject,
    trialAvailable: wire.trial_available ?? false,
    canDownload: wire.can_download,
    canUseAi: wire.can_use_ai,
    aiRequestsLeft: wire.ai_requests_left,
    subscriptionExpiresAt: wire.subscription_expires_at,
    subscriptionTitle: wire.subscription_title,
    lockedReason: wire.locked_reason,
  };
}

export async function fetchRealAccessStatus(subjectId: string): Promise<AccessStatus> {
  return toAccessStatus(await apiFetch(`/api/v1/access/${encodeURIComponent(subjectId)}`));
}

export async function enterSubject(subjectId: string): Promise<AccessStatus> {
  const result = await apiFetch<{access: AccessStatusWire}>(`/api/v1/access/${encodeURIComponent(subjectId)}/enter`, {method: "POST"});
  return toAccessStatus(result.access);
}

type AnatomyRunWire = Omit<AnatomyRun, "questions"> & {questions: AnatomyExamQuestionWire[]};
function toRun(run: AnatomyRunWire): AnatomyRun {
  return {...run, questions: run.questions.map(toAnatomyExamQuestion)};
}
export async function startAnatomyRun(kind: AnatomyRun["kind"], partId?: number, rating = false): Promise<AnatomyRun> {
  return toRun(await apiFetch<AnatomyRunWire>("/api/v1/anatomy/exam/runs", {method: "POST", body: JSON.stringify({kind, part_id: partId, rating})}));
}
export async function activeAnatomyRun(): Promise<AnatomyRun | null> {
  const run = await apiFetch<AnatomyRunWire | null>("/api/v1/anatomy/exam/runs/active");
  return run ? toRun(run) : null;
}
export async function answerAnatomyRun(runId: string, position: number, selectedIndex: number): Promise<AnatomyExamAnswerResult> {
  const wire = await apiFetch<AnatomyExamAnswerWire>(`/api/v1/anatomy/exam/runs/${encodeURIComponent(runId)}/answer`, {method: "POST", body: JSON.stringify({position, selected_index: selectedIndex})});
  return {correct: wire.correct, correctIndex: wire.correct_index, correctLetter: wire.correct_letter, correctText: wire.correct_text, explanation: wire.explanation};
}

export function fetchAnatomyPreferences(): Promise<{rating: boolean}> {
  return apiFetch("/api/v1/anatomy/exam/preferences");
}
export function setAnatomyPreferences(rating: boolean): Promise<{rating: boolean}> {
  return apiFetch("/api/v1/anatomy/exam/preferences", {method: "POST", body: JSON.stringify({rating})});
}
export interface AnatomyRatings {
  own_rank: number | null;
  entries: {rank: number; name: string; correct?: number; total?: number; best_correct?: number; best_total?: number; attempts: number}[];
}
export function fetchAnatomyRatings(kind: "part" | "flash"): Promise<AnatomyRatings> {
  return apiFetch(`/api/v1/anatomy/exam/ratings/${kind}`);
}

export async function fetchRealSubscriptionSummary(): Promise<AccessStatus> {
  return toAccessStatus(await apiFetch("/api/v1/subscription"));
}

/** Собирает UserProfile (app-тип, см. lib/types.ts) из ДВУХ источников — см. schemas.py на
 * бэкенде за тем, почему они не слиты в один ответ: authProfile (из initData, всегда самый
 * свежий first_name/username/фото) и /me (referral_count и т.п., которых в initData нет вообще).
 * firstName/username предпочитают authProfile — /me их читает из stats.json, где может быть
 * пусто у пользователя, которого бот никогда не видел, хотя Telegram явно назвал его имя прямо
 * сейчас. */
export function mergeProfile(authProfile: AuthProfile, me: RealMe): UserProfile {
  return {
    id: me.userId,
    firstName: authProfile.firstName ?? me.firstName ?? "Студент",
    lastName: authProfile.lastName,
    username: authProfile.username ?? me.username,
    photoUrl: authProfile.photoUrl,
    referralCount: me.referralCount,
    referralCountThisMonth: me.referralCountThisMonth,
  };
}

// ==================== контент (только реально подключённые предметы) ====================
// См. web_api/content.py на бэкенде -- сегодня это ровно Биохимия/Фармакология/Латынь/
// Правоведение (generated_courses/*.json). Любой другой subject_id вернёт 404 -- lib/api.ts сам
// решает, для кого вообще пробовать эти вызовы, здесь только чистая передача.

interface SubjectSummaryWire {
  id: string;
  title: string;
  emoji: string;
  description: string | null;
  course: 1 | 2;
  has_ai: boolean;
  maintenance?: boolean;
  maintenance_reason?: string | null;
}

interface SubjectDetailWire extends SubjectSummaryWire {
  sections: Array<{ id: string; title: string; item_count: number; kind: "flat" | "grouped" }>;
}

const ACCENT_BY_SUBJECT_ID: Record<string, string> = {
  biochemistry: "biochemistry",
  pharmacology: "pharmacology",
  latin: "latin",
  law: "law",
  physiology: "physiology",
  operative_surgery: "operative-surgery",
  anatomy: "anatomy",
  histology: "histology",
  biology: "biology",
  chemistry: "chemistry",
  physics: "physics",
};

function toSubjectSummary(wire: SubjectSummaryWire): SubjectSummary {
  return {
    id: wire.id,
    title: wire.title,
    accent: ACCENT_BY_SUBJECT_ID[wire.id] ?? "biochemistry",
    tag: wire.maintenance ? "Техобслуживание" : (wire.has_ai ? "VMEDA AI" : "Курс"),
    course: wire.course,
    readiness: null, // прогресс/готовность для реальных предметов ещё не подключены (см. README web_api)
    locked: wire.maintenance ?? false,
    hasAi: wire.has_ai,
    lockedReason: wire.maintenance_reason ?? undefined,
  };
}

export async function fetchRealSubjects(): Promise<SubjectSummary[]> {
  const wire: SubjectSummaryWire[] = await apiFetch("/api/v1/subjects");
  return wire.map(toSubjectSummary);
}

export async function fetchRealSubjectDetail(subjectId: string): Promise<SubjectDetail> {
  const wire: SubjectDetailWire = await apiFetch(`/api/v1/subjects/${encodeURIComponent(subjectId)}`);
  const sections: ContentSection[] = wire.sections.map((s) => ({
    id: s.id,
    title: s.title,
    itemCount: s.item_count,
    kind: s.kind,
  }));
  return { ...toSubjectSummary(wire), sections };
}

type SectionContentsWire =
  | { id: string; title: string; kind: "flat"; items: Array<{ id: string; title: string; order: number; total: number }> }
  | {
      id: string;
      title: string;
      kind: "grouped";
      // locked/locked_reason присутствуют только у Анатомии (см. web_api/routers/subjects.py::
      // _annotate_anatomy_groups) -- у остальных группированных разделов их нет вообще.
      groups: Array<{ id: string; title: string; item_count: number; locked?: boolean; locked_reason?: string | null }>;
    };

export async function fetchRealSection(subjectId: string, sectionId: string): Promise<SectionContents> {
  const wire: SectionContentsWire = await apiFetch(
    `/api/v1/subjects/${encodeURIComponent(subjectId)}/sections/${encodeURIComponent(sectionId)}`
  );
  if (wire.kind === "grouped") {
    return {
      kind: "grouped",
      groups: wire.groups.map((g) => ({
        id: g.id,
        title: g.title,
        itemCount: g.item_count,
        locked: g.locked,
        lockedReason: g.locked_reason,
      })),
    };
  }
  return {
    kind: "flat",
    items: wire.items.map((i) => ({ id: i.id, title: i.title, order: i.order, total: i.total })),
  };
}

interface GroupDetail {
  id: string;
  title: string;
  items: SectionItemRef[];
}

export async function fetchRealGroup(subjectId: string, sectionId: string, groupId: string): Promise<GroupDetail> {
  return apiFetch(
    `/api/v1/subjects/${encodeURIComponent(subjectId)}/sections/${encodeURIComponent(sectionId)}/groups/${encodeURIComponent(groupId)}`
  );
}

interface MaterialWire {
  id: string;
  title: string;
  content_html: string;
  sources: string[];
  order: number;
  total: number;
  group_id: string | null;
  prev_id: string | null;
  next_id: string | null;
  media: Array<{ path: string; caption: string }>;
  quiz: { options: string[] } | null;
}

interface QuizAnswerResponseWire {
  correct: boolean;
  correct_index: number;
}

export interface QuizAnswerResult {
  correct: boolean;
  correctIndex: number;
}

/** correct_index раскрывается только этим запросом, ПОСЛЕ того как пользователь уже выбрал
 * вариант -- см. web_api/content.py::check_quiz_answer и docstring MaterialDetail.quiz. */
export async function checkQuizAnswer(
  subjectId: string,
  sectionId: string,
  itemId: string,
  selectedIndex: number
): Promise<QuizAnswerResult> {
  const wire: QuizAnswerResponseWire = await apiFetch(
    `/api/v1/materials/${encodeURIComponent(subjectId)}/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}/answer`,
    { method: "POST", body: JSON.stringify({ selected_index: selectedIndex }) }
  );
  return { correct: wire.correct, correctIndex: wire.correct_index };
}

// ==================== экзаменационный тест по анатомии ====================

interface AnatomyExamPartWire {
  id: number;
  title: string;
  topics: string;
  question_count: number;
}

interface AnatomyExamQuestionWire {
  id: string;
  num: number;
  question: string;
  option_letters: string[];
  options: string[];
}

interface AnatomyExamAnswerWire {
  correct: boolean;
  correct_index: number;
  correct_letter: string;
  correct_text: string;
  explanation: string;
}

function toAnatomyExamQuestion(wire: AnatomyExamQuestionWire): AnatomyExamQuestion {
  return {
    id: wire.id,
    num: wire.num,
    question: wire.question,
    optionLetters: wire.option_letters,
    options: wire.options,
  };
}

export async function fetchAnatomyExamParts(): Promise<AnatomyExamPart[]> {
  const wire = await apiFetch<AnatomyExamPartWire[]>("/api/v1/anatomy/exam/parts");
  return wire.map((part) => ({
    id: part.id,
    title: part.title,
    topics: part.topics,
    questionCount: part.question_count,
  }));
}

export async function fetchAnatomyExamPartQuestions(partId: number): Promise<AnatomyExamQuestion[]> {
  const wire = await apiFetch<AnatomyExamQuestionWire[]>(`/api/v1/anatomy/exam/parts/${partId}/questions`);
  return wire.map(toAnatomyExamQuestion);
}

export async function fetchAnatomyExamFlashQuestions(): Promise<AnatomyExamQuestion[]> {
  const wire = await apiFetch<AnatomyExamQuestionWire[]>("/api/v1/anatomy/exam/flash?limit=50");
  return wire.map(toAnatomyExamQuestion);
}

export async function checkAnatomyExamAnswer(
  questionNum: number,
  selectedIndex: number,
): Promise<AnatomyExamAnswerResult> {
  const wire = await apiFetch<AnatomyExamAnswerWire>(
    `/api/v1/anatomy/exam/questions/${questionNum}/answer`,
    { method: "POST", body: JSON.stringify({ selected_index: selectedIndex }) },
  );
  return {
    correct: wire.correct,
    correctIndex: wire.correct_index,
    correctLetter: wire.correct_letter,
    correctText: wire.correct_text,
    explanation: wire.explanation,
  };
}

// ==================== гистология · ЭКЗАМЕН ====================

interface HistologySpecimenWire {
  id: string;
  number: number;
  title: string;
  stain: string | null;
  magnification: string | null;
  group_id: string;
  group_title: string;
  image_count: number;
  practical_available: boolean;
}

interface HistologyStatsWire {
  total_specimens: number;
  attempts: number;
  known: number;
  wrong: number;
  accuracy_percent: number;
  mastered_specimens: number;
  active_mistakes: number;
  mistake_ids: string[];
}

function toHistologySummary(wire: HistologySpecimenWire): HistologySpecimenSummary {
  return {
    id: wire.id,
    number: wire.number,
    title: wire.title,
    stain: wire.stain,
    magnification: wire.magnification,
    groupId: wire.group_id,
    groupTitle: wire.group_title,
    imageCount: wire.image_count,
    practicalAvailable: wire.practical_available,
  };
}

function toHistologyStats(wire: HistologyStatsWire): HistologyStats {
  return {
    totalSpecimens: wire.total_specimens,
    attempts: wire.attempts,
    known: wire.known,
    wrong: wire.wrong,
    accuracy: wire.accuracy_percent,
    mastered: wire.mastered_specimens,
    activeMistakes: wire.active_mistakes,
    mistakeIds: wire.mistake_ids,
  };
}

export async function fetchHistologyCatalog(): Promise<HistologyCatalog> {
  const wire = await apiFetch<{
    title: string;
    total_specimens: number;
    groups: Array<{ id: string; title: string; menu_title: string; specimens: HistologySpecimenWire[] }>;
  }>("/api/v1/histology/exam/catalog");
  return {
    title: wire.title,
    totalSpecimens: wire.total_specimens,
    groups: wire.groups.map((group) => ({
      id: group.id,
      title: group.title,
      menuTitle: group.menu_title,
      specimens: group.specimens.map(toHistologySummary),
    })),
  };
}

export async function fetchHistologyStats(): Promise<HistologyStats> {
  return toHistologyStats(await apiFetch<HistologyStatsWire>("/api/v1/histology/exam/stats"));
}

export async function fetchHistologySpecimen(specimenId: string): Promise<HistologySpecimen> {
  const wire = await apiFetch<HistologySpecimenWire & {
    protocol: string;
    images: string[];
    markers: Array<{ x: number; y: number; label: string }>;
  }>(`/api/v1/histology/exam/specimens/${encodeURIComponent(specimenId)}`);
  return {
    ...toHistologySummary(wire),
    protocol: wire.protocol,
    images: wire.images.map(absoluteApiUrl),
    markers: wire.markers,
  };
}

export async function fetchHistologyPractical(
  scope: "all" | "mistakes" | string = "all",
  limit = 10,
): Promise<HistologyPracticalQuestion[]> {
  const wire = await apiFetch<Array<{ id: string; position: number; image_url: string; attempt_id: string }>>(
    `/api/v1/histology/exam/practical?scope=${encodeURIComponent(scope)}&limit=${limit}`,
  );
  return wire.map((item) => ({ id: item.id, position: item.position, imageUrl: absoluteApiUrl(item.image_url), attemptId: item.attempt_id }));
}

export async function revealHistologyAnswer(specimenId: string): Promise<HistologySpecimenSummary & { protocol: string }> {
  const wire = await apiFetch<HistologySpecimenWire & { protocol: string }>(
    `/api/v1/histology/exam/specimens/${encodeURIComponent(specimenId)}/reveal`,
    { method: "POST" },
  );
  return { ...toHistologySummary(wire), protocol: wire.protocol };
}

export async function gradeHistologyAnswer(
  specimenId: string,
  known: boolean,
  scope: string,
  attemptId: string,
): Promise<HistologyStats> {
  const wire = await apiFetch<HistologyStatsWire>(
    `/api/v1/histology/exam/specimens/${encodeURIComponent(specimenId)}/grade`,
    { method: "POST", body: JSON.stringify({ known, scope, attempt_id: attemptId }) },
  );
  return toHistologyStats(wire);
}

// ==================== VMedA AI ====================
// Единственный роутер web_api, который реально вызывает AI-пайплайн бота (см.
// web_api/routers/ai.py) -- всё остальное здесь только отдаёт уже готовый контент.

interface AiSolveResponseWire {
  answer_html: string;
  low_confidence: boolean;
  confidence_note: string | null;
  requests_left: number | null;
  session_active: boolean;
}

export interface AiSolveResult {
  answerHtml: string;
  lowConfidence: boolean;
  confidenceNote: string | null;
  requestsLeft: number | null;
  sessionActive: boolean;
}

export interface AiSolveInput {
  subjectId?: string;
  mode: "text" | "photo";
  text?: string;
  imageBase64?: string;
}

export async function solveAiTask(input: AiSolveInput): Promise<AiSolveResult> {
  const wire: AiSolveResponseWire = await apiFetch("/api/v1/ai/solve", {
    method: "POST",
    body: JSON.stringify({
      subject_id: input.subjectId,
      mode: input.mode,
      text: input.text,
      image_base64: input.imageBase64,
    }),
  });
  return {
    answerHtml: wire.answer_html,
    lowConfidence: wire.low_confidence,
    confidenceNote: wire.confidence_note,
    requestsLeft: wire.requests_left,
    sessionActive: wire.session_active,
  };
}

export async function fetchRealMaterial(
  subjectId: string,
  sectionId: string,
  itemId: string
): Promise<MaterialDetail> {
  const wire: MaterialWire = await apiFetch(
    `/api/v1/materials/${encodeURIComponent(subjectId)}/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}`
  );
  return {
    id: wire.id,
    subjectId,
    sectionId,
    title: wire.title,
    status: "in_progress", // прогресс для реальных предметов ещё не подключён, см. README web_api
    order: wire.order,
    totalInSection: wire.total,
    groupId: wire.group_id,
    prevId: wire.prev_id,
    nextId: wire.next_id,
    blocks: [],
    rawHtml: wire.content_html,
    sources: wire.sources,
    media: wire.media.map((m, index) => ({
      url: `${API_BASE_URL}/api/v1/materials/${encodeURIComponent(subjectId)}/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}/media/${index}`,
      caption: m.caption,
    })),
    quiz: wire.quiz,
  };
}

interface LearningMaterialWire {
  subject_id: string;
  section_id: string;
  material_id: string;
  subject_title: string;
  section_title: string;
  material_title: string;
  material_order: number;
  total_in_section: number;
  last_opened_at: string;
}

interface LearningStateWire {
  completed_keys: string[];
  favorites: LearningMaterialWire[];
  last_material: LearningMaterialWire | null;
  completed_by_subject: Record<string, number>;
  completed_total: number;
  quiz_attempts: number;
  quiz_correct: number;
}

function toLearningMaterial(wire: LearningMaterialWire) {
  return {
    subjectId: wire.subject_id,
    sectionId: wire.section_id,
    materialId: wire.material_id,
    subjectTitle: wire.subject_title,
    sectionTitle: wire.section_title,
    materialTitle: wire.material_title,
    materialOrder: wire.material_order,
    totalInSection: wire.total_in_section,
    lastOpenedAt: wire.last_opened_at,
  };
}

function toLearningState(wire: LearningStateWire): LearningState {
  return {
    completedKeys: wire.completed_keys,
    favorites: wire.favorites.map(toLearningMaterial),
    lastMaterial: wire.last_material ? toLearningMaterial(wire.last_material) : null,
    completedBySubject: wire.completed_by_subject,
    completedTotal: wire.completed_total,
    quizAttempts: wire.quiz_attempts,
    quizCorrect: wire.quiz_correct,
  };
}

export async function fetchLearningState(): Promise<LearningState> {
  return toLearningState(await apiFetch<LearningStateWire>("/api/v1/learning/state"));
}

export interface MaterialTouchInput {
  subjectId: string;
  sectionId: string;
  materialId: string;
  subjectTitle?: string;
  sectionTitle?: string;
  materialTitle: string;
  materialOrder: number;
  totalInSection: number;
}

export async function touchLearningMaterial(input: MaterialTouchInput): Promise<LearningState> {
  return toLearningState(await apiFetch<LearningStateWire>("/api/v1/learning/materials/touch", {
    method: "POST",
    body: JSON.stringify({
      subject_id: input.subjectId,
      section_id: input.sectionId,
      material_id: input.materialId,
      subject_title: input.subjectTitle ?? "",
      section_title: input.sectionTitle ?? "",
      material_title: input.materialTitle,
      material_order: input.materialOrder,
      total_in_section: input.totalInSection,
    }),
  }));
}

export async function setLearningFlag(
  input: Pick<MaterialTouchInput, "subjectId" | "sectionId" | "materialId">,
  flag: "completed" | "favorite",
  value: boolean,
): Promise<LearningState> {
  const path = [input.subjectId, input.sectionId, input.materialId].map(encodeURIComponent).join("/");
  return toLearningState(await apiFetch<LearningStateWire>(`/api/v1/learning/materials/${path}/${flag}`, {
    method: "POST",
    body: JSON.stringify({ value }),
  }));
}

export interface SubscriptionPlan {
  id: number; title: string; short: string; price_stars: number; price_rub: number; card_transfer_url: string; duration_days: number | null;
  expires_at: string | null; benefits: string[]; badge: string | null; ai_limit: number | null;
  ai_period: string | null; courses: number[]; unavailable_reason: string | null;
  subject_options: { id: string; title: string; unavailable_reason: string | null }[];
}
export interface SubscriptionCatalog {
  plans: SubscriptionPlan[]; sbp_available: boolean;
  current: { active: boolean; tier_id: number | null; title: string | null; expires_at: string | null;
    benefits: string[]; ai_remaining: number | null; ai_limit: number | null; ai_period: string | null;
    access: { id: string; title: string; available: boolean }[] };
}
export function fetchSubscriptionCatalog(): Promise<SubscriptionCatalog> {
  return apiFetch("/api/v1/subscriptions/catalog");
}
export function createSubscriptionInvoice(tierId: number, subject?: string): Promise<{url: string; payment_id: string}> {
  return apiFetch("/api/v1/subscriptions/invoice", {method: "POST", body: JSON.stringify({tier_id: tierId, subject})});
}
export function fetchSubscriptionPayment(id: string): Promise<{status: "processing" | "applied" | "review" | "failed" | "cancelled"}> {
  return apiFetch(`/api/v1/subscriptions/payments/${encodeURIComponent(id)}`);
}

export function createSbpSubscription(tierId: number, requestKey: string, subject?: string): Promise<{url: string; payment_id: string}> {
  return apiFetch("/api/v1/subscriptions/sbp", {method: "POST", body: JSON.stringify({tier_id: tierId, subject, request_key: requestKey})});
}
export interface BillingPayment { id: string; tier_id: number; subject: string | null; amount_minor: number; created: number; state: string; reason: string | null; url: string | null }
export function fetchBillingHistory(): Promise<{payments: BillingPayment[]}> {
  return apiFetch("/api/v1/subscriptions/history");
}
