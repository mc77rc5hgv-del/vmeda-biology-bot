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
}

export interface SubjectDetail extends SubjectSummary {
  sections: ContentSection[];
}

export interface MaterialRef {
  id: string;
  subjectId: string;
  sectionId: string;
  title: string;
  status: ProgressStatus;
  /** Порядковый номер темы и общее число тем раздела — "Тема 12 из 18" на карточке продолжения. */
  order: number;
  totalInSection: number;
}

export interface MaterialBlock {
  kind: "short_explanation" | "full_text" | "must_remember" | "confusions" | "diagram" | "quick_review";
  title: string;
  body: string;
}

export interface MaterialDetail extends MaterialRef {
  blocks: MaterialBlock[];
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
