// Тонкий слой поверх настоящего web_api (см. web_api/README.md в репозитории бота) — единственное
// место, которое знает про формат данных на проводе (snake_case, ровно как в web_api/schemas.py)
// и переводит его в app-типы из lib/types.ts. lib/api.ts (диспетчер, решающий mock vs реальный
// вызов) — единственный, кто это импортирует; компоненты про существование этого файла не знают.
import type {
  ContentSection,
  MaterialDetail,
  SectionContents,
  SectionItemRef,
  SubjectDetail,
  SubjectSummary,
  UserProfile,
} from "./types";
import { clearStoredSessionToken, getStoredSessionToken, storeSessionToken } from "./session";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

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
    if (response.status === 401) clearStoredSessionToken(); // токен протух/невалиден — не держим мёртвый
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
}

interface SubjectDetailWire extends SubjectSummaryWire {
  sections: Array<{ id: string; title: string; item_count: number; kind: "flat" | "grouped" }>;
}

const ACCENT_BY_SUBJECT_ID: Record<string, string> = {
  biochemistry: "biochemistry",
  pharmacology: "pharmacology",
  latin: "latin",
  law: "law",
};

function toSubjectSummary(wire: SubjectSummaryWire): SubjectSummary {
  return {
    id: wire.id,
    title: wire.title,
    accent: ACCENT_BY_SUBJECT_ID[wire.id] ?? "biochemistry",
    tag: wire.has_ai ? "VMEDA AI" : "Курс",
    course: wire.course,
    readiness: null, // прогресс/готовность для реальных предметов ещё не подключены (см. README web_api)
    locked: false, // ни один "динамический" предмет сегодня не гейтится, см. content.py/CLAUDE.md
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
  | { id: string; title: string; kind: "grouped"; groups: Array<{ id: string; title: string; item_count: number }> };

export async function fetchRealSection(subjectId: string, sectionId: string): Promise<SectionContents> {
  const wire: SectionContentsWire = await apiFetch(
    `/api/v1/subjects/${encodeURIComponent(subjectId)}/sections/${encodeURIComponent(sectionId)}`
  );
  if (wire.kind === "grouped") {
    return {
      kind: "grouped",
      groups: wire.groups.map((g) => ({ id: g.id, title: g.title, itemCount: g.item_count })),
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
  };
}
