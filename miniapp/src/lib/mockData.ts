// Тестовые данные Этапа 2 (дизайн-прототип). НИКАКОГО реального API/пользователя здесь нет —
// это заглушка ровно по форме контракта из lib/types.ts, чтобы верстать экраны уже сейчас.
//
// Список предметов и разделов взят из реального аудита репозитория бота (Этап 1), а не выдуман:
// названия и структура разделов каждого предмета соответствуют тому, что уже есть в JSON-базах
// бота (tickets.json/questions.json, anatomy.json, physiology.json, operative_surgery.json,
// generated_courses/*.json) — см. отчёт Этапа 1. Сам ТЕКСТ уроков/вопросов ниже — заглушка
// (Lorem-подобный текст), поскольку это дизайн-прототип, а не перенос контента.

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
import type { AiSolveResult } from "./apiClient";

export const mockUser: UserProfile = {
  id: 123456789,
  firstName: "Алексей",
  lastName: null,
  username: "alex_vmeda",
  photoUrl: null,
  referralCount: 4,
  referralCountThisMonth: 1,
};

export const mockDashboard: DashboardStats = {
  streakDays: 7,
  xp: 420,
  readinessPercent: 68,
  dailyGoalMinutes: 30,
  minutesLeftToday: 20,
};

export const mockContinue: ContinueItem = {
  subjectId: "biochemistry",
  subjectTitle: "Биохимия",
  sectionTitle: "Зачёт",
  materialTitle: "Тема 12",
  order: 12,
  totalInSection: 18,
};

export const mockSubjects: SubjectSummary[] = [
  // ---- 1 курс ----
  { id: "physics", title: "Физика", accent: "physics", tag: "Билеты", course: 1, readiness: 42, locked: false, hasAi: true },
  { id: "chemistry", title: "Химия", accent: "chemistry", tag: "Лабораторные", course: 1, readiness: 35, locked: false, hasAi: true },
  { id: "biology", title: "Биология", accent: "biology", tag: "Билеты", course: 1, readiness: 71, locked: false, hasAi: true },
  { id: "anatomy", title: "Анатомия", accent: "anatomy", tag: "10 модулей", course: 1, readiness: 24, locked: false, hasAi: true },
  { id: "histology", title: "Гистология", accent: "histology", tag: "71 препарат", course: 1, readiness: null, locked: true, lockedReason: "Нужно 2 реферала в этом месяце", hasAi: true },
  { id: "latin", title: "Латинский язык", accent: "latin", tag: "Зачёт", course: 1, readiness: 10, locked: false, hasAi: true },
  { id: "law", title: "Правоведение", accent: "law", tag: "81 вопрос", course: 1, readiness: 0, locked: false },
  // ---- 2 курс ----
  { id: "physiology", title: "Нормальная физиология", accent: "physiology", tag: "Рубежные", course: 2, readiness: 55, locked: false, hasAi: true },
  { id: "operative_surgery", title: "Оперативная хирургия", accent: "operative-surgery", tag: "4 тома", course: 2, readiness: 18, locked: false, hasAi: true },
  { id: "biochemistry", title: "Биохимия", accent: "biochemistry", tag: "68%", course: 2, readiness: 68, locked: false, hasAi: true },
  { id: "pharmacology", title: "Фармакология", accent: "pharmacology", tag: "Контрольные", course: 2, readiness: 8, locked: false, hasAi: true },
];

const subjectSections: Record<string, SubjectDetail["sections"]> = {
  physics: [
    { id: "test", title: "Тестовая часть", itemCount: 186, kind: "flat" },
    { id: "grade45", title: "Вопросы на 4/5", itemCount: 60, kind: "flat" },
    { id: "extra", title: "Доп. вопросы от преподавателей", itemCount: 13, kind: "flat" },
    { id: "tasks", title: "Задачи по темам", itemCount: 58, kind: "grouped" },
    { id: "task_tickets", title: "Билеты с задачами", itemCount: 40, kind: "grouped" },
    { id: "theory_tickets", title: "Билеты теоретической части", itemCount: 60, kind: "grouped" },
    { id: "test_tickets", title: "Тестовые билеты", itemCount: 123, kind: "grouped" },
  ],
  chemistry: [
    { id: "theory", title: "Теория", itemCount: 16, kind: "flat" },
    { id: "tasks", title: "Задачи", itemCount: 75, kind: "grouped" },
    { id: "labs", title: "Лабораторные", itemCount: 6, kind: "flat" },
    { id: "theory_tickets", title: "Билеты теории", itemCount: 22, kind: "grouped" },
    { id: "practice_tickets", title: "Билеты практики", itemCount: 12, kind: "flat" },
  ],
  biology: [
    { id: "tickets", title: "Билеты", itemCount: 120, kind: "grouped" },
    { id: "questions", title: "Вопросы", itemCount: 185, kind: "flat" },
  ],
  anatomy: [
    { id: "course", title: "Курс", itemCount: 107, kind: "grouped" },
  ],
  histology: [
    { id: "specimens", title: "Препараты", itemCount: 71, kind: "grouped" },
  ],
  latin: [
    { id: "latin_credit", title: "Зачёт", itemCount: 1 },
  ],
  law: [
    { id: "theory", title: "Теория государства и права", itemCount: 14, kind: "flat" },
    { id: "constitutional", title: "Конституционное право", itemCount: 10, kind: "flat" },
    { id: "civil", title: "Гражданское право", itemCount: 12, kind: "flat" },
    { id: "family", title: "Семейное право", itemCount: 5, kind: "flat" },
    { id: "labor", title: "Трудовое право", itemCount: 21, kind: "flat" },
    { id: "administrative", title: "Административное право", itemCount: 3, kind: "flat" },
    { id: "criminal", title: "Уголовное право", itemCount: 8, kind: "flat" },
    { id: "medical", title: "Медицинское право", itemCount: 5, kind: "flat" },
    { id: "military", title: "Военная служба", itemCount: 3, kind: "flat" },
    { id: "international", title: "Международное право", itemCount: 6, kind: "flat" },
    { id: "social_norms", title: "Социальные нормы", itemCount: 1, kind: "flat" },
  ],
  physiology: [
    { id: "course", title: "Курс", itemCount: 23, kind: "flat" },
    { id: "boundary-controls", title: "Рубежные контроли", itemCount: 127, kind: "grouped" },
  ],
  operative_surgery: [
    { id: "volumes", title: "Тома", itemCount: 61, kind: "grouped" },
  ],
  biochemistry: [
    { id: "tests_and_controls", title: "Тесты и контрольные", itemCount: 1653, kind: "grouped" },
    { id: "credit", title: "Зачёт", itemCount: 109, kind: "flat" },
    { id: "exam", title: "Экзамен", itemCount: 230, kind: "grouped" },
  ],
  pharmacology: [
    { id: "course", title: "Курс", itemCount: 1174, kind: "grouped" },
    { id: "controls", title: "Контрольные", itemCount: 254, kind: "grouped" },
    { id: "credit", title: "Зачёт", itemCount: 221, kind: "grouped" },
    { id: "exam", title: "Экзамен", itemCount: 599, kind: "grouped" },
  ],
};

export function getSubjectDetail(subjectId: string): SubjectDetail | null {
  const summary = mockSubjects.find((s) => s.id === subjectId);
  if (!summary) return null;
  return { ...summary, sections: subjectSections[subjectId] ?? [] };
}

export function getMaterial(subjectId: string, sectionId: string, materialId: string): MaterialDetail | null {
  const subject = getSubjectDetail(subjectId);
  const section = subject?.sections.find((s) => s.id === sectionId);
  if (!subject || !section) return null;
  return {
    id: materialId,
    subjectId,
    sectionId,
    title: `Тема ${materialId}`,
    status: "in_progress",
    order: Number(materialId) || 1,
    totalInSection: section.itemCount || 1,
    blocks: [
      {
        kind: "short_explanation",
        title: "Короткое объяснение",
        body: "Краткое, буквально в несколько предложений, объяснение сути темы — то, что можно прочитать за минуту перед занятием.",
      },
      {
        kind: "full_text",
        title: "Полный материал",
        body: "Развёрнутый конспект темы с примерами и разбором механизмов. В реальном приложении сюда попадёт материал из соответствующей JSON-базы бота один в один, без изменений.",
      },
      {
        kind: "must_remember",
        title: "Главное запомнить",
        body: "— Ключевой факт №1\n— Ключевой факт №2\n— Ключевой факт №3",
      },
      {
        kind: "confusions",
        title: "Не путать",
        body: "Термин А ≠ термин Б — частая ошибка на экзамене.",
      },
      {
        kind: "quick_review",
        title: "Быстрое повторение",
        body: "Итог темы в одном абзаце — для повтора за 30 секунд перед зачётом.",
      },
    ],
  };
}

export function getTestSummary(subjectId: string): TestSummary {
  return {
    id: `${subjectId}-quiz`,
    subjectId,
    title: "Тренировочный тест",
    questionCount: 10,
    timeLimitSeconds: null,
  };
}

export function getTestQuestions(subjectId: string): TestQuestion[] {
  return Array.from({ length: 5 }, (_, i) => ({
    id: `${subjectId}-q${i + 1}`,
    question: `Вопрос ${i + 1} по теме — placeholder текста вопроса для прототипа интерфейса.`,
    options: ["Вариант А", "Вариант Б", "Вариант В", "Вариант Г"],
    correctIndex: i % 4,
  }));
}

/** Подписка — атрибут пользователя целиком, не конкретного предмета (см. Этап 1 аудита:
 * stats["subscriptions"][uid] хранит ОДНУ текущую подписку на человека) — отдельный мок,
 * не переиспользующий getAccessStatus(subjectId) один в один, чтобы не создавать иллюзию,
 * что у каждого предмета своя подписка. */
export const mockSubscriptionSummary: AccessStatus = {
  canOpenSubject: true,
  canDownload: false,
  canUseAi: true,
  aiRequestsLeft: 12,
  subscriptionExpiresAt: "2027-01-01T00:00:00Z",
  subscriptionTitle: "Весь первый курс",
  lockedReason: null,
};

export function getAccessStatus(subjectId: string): AccessStatus {
  const subject = mockSubjects.find((s) => s.id === subjectId);
  if (subject?.locked) {
    return {
      canOpenSubject: false,
      canDownload: false,
      canUseAi: false,
      aiRequestsLeft: 0,
      subscriptionExpiresAt: null,
      subscriptionTitle: null,
      lockedReason: subject.lockedReason ?? "Раздел недоступен",
    };
  }
  return {
    canOpenSubject: true,
    canDownload: false,
    canUseAi: true,
    aiRequestsLeft: 12,
    subscriptionExpiresAt: "2027-01-01T00:00:00Z",
    subscriptionTitle: "Весь первый курс",
    lockedReason: null,
  };
}

/** Вне Telegram (обычный браузер, локальная разработка без сессии) настоящий web_api/routers/ai.py
 * недостижим — он требует реального user_id из провалидированной initData (см. docstring там).
 * Эта заглушка только для верстки экрана VMEDA AI без сети, ровно как остальной lib/mockData.ts —
 * реальный ответ приходит через apiClient.solveAiTask, когда сессия есть (см. lib/api.ts). */
export function getAiMockAnswer(mode: "text" | "photo"): AiSolveResult {
  const body =
    mode === "photo"
      ? "По материалам курса: краткий разбор задания появится здесь после открытия из бота VMEDA — это макет без реального AI-пайплайна."
      : "Краткий ответ — заглушка для прототипа вне Telegram. Открой мини-приложение из бота, чтобы получить настоящий разбор от VMEDA AI.";
  return {
    answerHtml: `<p>${body}</p>`,
    lowConfidence: mode === "photo",
    confidenceNote: mode === "photo" ? "Фото не отправлялось — это демонстрационный ответ вне Telegram." : null,
    requestsLeft: 12,
    sessionActive: true,
  };
}
