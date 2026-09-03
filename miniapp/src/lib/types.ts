// Единый контентный контракт (см. ТЗ §14) и модели прогресса/доступа (§13, §16).
// Именно ЭТИ типы backend должен будет отдавать через /api/v1/... — на Этапе 2 их же заполняет
// mockData.ts, чтобы верстать экраны не дожидаясь API.

export type CourseId = 1 | 2;

export type ProgressStatus =
  | "not_started"
  | "in_progress"
  | "completed"
  | "needs_review"
  | "mastered";

export interface SubjectSummary {
  id: string;
  title: string;
  /** Токен цвета из tokens.css, напр. "physiology" -> var(--subject-physiology). */
  accent: string;
  /** Однословная подпись под названием предмета на карточке (см. §9 ТЗ: "Рубежные", "31 станция", "68%"). */
  tag: string;
  course: CourseId;
  /** null — готовность ещё не считалась (пользователь не открывал предмет). */
  readiness: number | null;
  locked: boolean;
  /** Короткая причина блокировки для локализованного текста на карточке, если locked. */
  lockedReason?: string;
}

export interface ContentSection {
  id: string;
  title: string;
  /** Число элементов раздела — для подписи вида "18 тем" без отдельного запроса. */
  itemCount: number;
  /** "grouped" — только у реально подключённых предметов (см. lib/apiClient.ts), где раздел
   * бьётся на подгруппы (сегодня единственный пример — Фармакология, раздел "Курс", 6 групп).
   * Отсутствует (= "flat") у всех остальных, включая все mock-предметы Этапа 2. */
  kind?: "flat" | "grouped";
}

export interface SubjectDetail extends SubjectSummary {
  sections: ContentSection[];
}

/** Один элемент списка при просмотре раздела (SectionPage) или группы (GroupPage) — ДО открытия
 * самого материала. Только для реально подключённых предметов: у mock-предметов такого списка
 * нет (см. §22 ТЗ — "не придумывай материалы"), Subject.tsx для них по-прежнему прыгает сразу к
 * материалу, как в Этапе 2. */
export interface SectionItemRef {
  id: string;
  title: string;
  order: number;
  total: number;
}

export interface SectionGroupRef {
  id: string;
  title: string;
  itemCount: number;
}

export type SectionContents =
  | { kind: "flat"; items: SectionItemRef[] }
  | { kind: "grouped"; groups: SectionGroupRef[] };

export interface MaterialRef {
  id: string;
  subjectId: string;
  sectionId: string;
  title: string;
  status: ProgressStatus;
  /** Порядковый номер темы и общее число тем раздела — "Тема 12 из 18" на карточке продолжения. */
  order: number;
  totalInSection: number;
  /** Только у материалов из группированного раздела (см. SectionContents выше) — нужен, чтобы
   * кнопка "назад" на экране материала вела в правильную группу, а не в раздел целиком. */
  groupId?: string | null;
}

export interface MaterialBlock {
  kind: "short_explanation" | "full_text" | "must_remember" | "confusions" | "diagram" | "quick_review";
  title: string;
  body: string;
}

export interface MaterialMedia {
  url: string;
  caption: string;
}

export interface MaterialDetail extends MaterialRef {
  /** Ровно один из двух источников содержимого реален для конкретного материала:
   * `blocks` — многоблочный конспект (Этап 2, mock-предметы, см. lib/mockData.ts);
   * `rawHtml` — один HTML-блок как есть из реальной базы курса (см. web_api/content.py) —
   * настоящие уроки Биохимии/Фармакологии/Латыни/Правоведения устроены именно так, без деления
   * на "короткое объяснение"/"главное запомнить" и т.п., и придумывать такое деление для них
   * значило бы редактировать реальный контент, а не просто иначе его показывать. */
  blocks: MaterialBlock[];
  rawHtml?: string;
  sources?: string[];
  media?: MaterialMedia[];
  /** id соседних материалов для реального контента (см. web_api/content.py) — не числовые
   * order+1/order-1, как у mock-материалов (lib/mockData.ts), а готовые id с бэкенда, потому что
   * реальные id ("core_p1_1" и т.п.) не образуют предсказуемую последовательность. undefined у
   * mock-материалов — там навигация считается через order/totalInSection на самой странице. */
  prevId?: string | null;
  nextId?: string | null;
}

export interface TestQuestion {
  id: string;
  question: string;
  options: string[];
  /** Индекс правильного варианта. Backend никогда не должен присылать это до ответа пользователя
   * в реальном API — здесь он есть только потому, что Этап 2 не имеет сервера вообще (см. lib/mockData.ts). */
  correctIndex: number;
}

export interface TestSummary {
  id: string;
  subjectId: string;
  title: string;
  questionCount: number;
  /** Для экзаменационного режима — таймер в секундах, иначе null. */
  timeLimitSeconds: number | null;
}

export interface ProgressEntry {
  subjectId: string;
  sectionId: string;
  materialId: string;
  status: ProgressStatus;
  score: number | null;
  attempts: number;
  correctAnswers: number;
  totalAnswers: number;
  lastOpenedAt: string | null;
  nextReviewAt: string | null;
}

export interface DashboardStats {
  streakDays: number;
  xp: number;
  /** Итоговая готовность по формуле §13 ТЗ — считается backend'ом, фронт её не пересчитывает. */
  readinessPercent: number;
  dailyGoalMinutes: number;
  minutesLeftToday: number;
}

export interface ContinueItem {
  subjectId: string;
  subjectTitle: string;
  sectionTitle: string;
  materialTitle: string;
  order: number;
  totalInSection: number;
}

/** Права доступа — решает ТОЛЬКО backend (§16 ТЗ), фронт лишь отображает эти уже посчитанные поля. */
export interface AccessStatus {
  canOpenSubject: boolean;
  canDownload: boolean;
  canUseAi: boolean;
  aiRequestsLeft: number | null;
  subscriptionExpiresAt: string | null;
  subscriptionTitle: string | null;
  lockedReason: string | null;
}

export interface UserProfile {
  id: number;
  firstName: string;
  lastName: string | null;
  username: string | null;
  photoUrl: string | null;
  referralCount: number;
  referralCountThisMonth: number;
}
