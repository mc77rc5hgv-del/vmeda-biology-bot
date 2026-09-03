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
  { id: "physics", title: "Физика", accent: "physics", tag: "Билеты", course: 1, readiness: 42, locked: false },
  { id: "chemistry", title: "Химия", accent: "chemistry", tag: "Лабораторные", course: 1, readiness: 35, locked: false },
  { id: "biology", title: "Биология", accent: "biology", tag: "Флеш-карточки", course: 1, readiness: 71, locked: false },
  { id: "anatomy", title: "Анатомия", accent: "anatomy", tag: "10 модулей", course: 1, readiness: 24, locked: false },
  { id: "histology", title: "Гистология", accent: "histology", tag: "Тренажёр", course: 1, readiness: null, locked: true, lockedReason: "Нужно 2 реферала в этом месяце" },
  { id: "latin", title: "Латинский язык", accent: "latin", tag: "Зачёт", course: 1, readiness: 10, locked: false },
  { id: "law", title: "Правоведение", accent: "law", tag: "81 вопрос", course: 1, readiness: 0, locked: false },
  // ---- 2 курс ----
  { id: "physiology", title: "Нормальная физиология", accent: "physiology", tag: "Рубежные", course: 2, readiness: 55, locked: false },
  { id: "operative-surgery", title: "Оперативная хирургия", accent: "operative-surgery", tag: "31 станция", course: 2, readiness: 18, locked: false },
  { id: "biochemistry", title: "Биохимия", accent: "biochemistry", tag: "68%", course: 2, readiness: 68, locked: false },
  { id: "pharmacology", title: "Фармакология", accent: "pharmacology", tag: "Контрольные", course: 2, readiness: 8, locked: false },
];

const subjectSections: Record<string, SubjectDetail["sections"]> = {
  physics: [
    { id: "theory", title: "Теория", itemCount: 24 },
    { id: "tickets", title: "Билеты", itemCount: 30 },
    { id: "tasks", title: "Задачи", itemCount: 40 },
  ],
  chemistry: [
    { id: "theory", title: "Теория", itemCount: 20 },
    { id: "practice", title: "Практика", itemCount: 18 },
    { id: "labs", title: "Лабораторные", itemCount: 12 },
    { id: "tickets", title: "Билеты", itemCount: 30 },
  ],
  biology: [
    { id: "tickets", title: "Билеты", itemCount: 30 },
    { id: "questions", title: "Вопросы", itemCount: 120 },
    { id: "flashcards", title: "Флеш-карточки", itemCount: 200 },
  ],
  anatomy: [
    { id: "course", title: "Курс", itemCount: 10 },
    { id: "exam", title: "Экзамен", itemCount: 3 },
  ],
  histology: [
    { id: "topics", title: "Темы", itemCount: 18 },
    { id: "trainer", title: "Тренажёр по препаратам", itemCount: 40 },
  ],
  latin: [
    { id: "course", title: "Курс", itemCount: 14 },
    { id: "ai", title: "VMEDA AI", itemCount: 0 },
  ],
  law: [
    { id: "questions", title: "Вопросы к зачёту", itemCount: 81 },
  ],
  physiology: [
    { id: "topics", title: "Темы", itemCount: 23 },
    { id: "quiz", title: "Тест", itemCount: 149 },
    { id: "boundary-controls", title: "Рубежные контроли", itemCount: 11 },
  ],
  "operative-surgery": [
    { id: "volumes", title: "Тома", itemCount: 4 },
    { id: "instruments", title: "Инструменты", itemCount: 11 },
    { id: "projections", title: "Проекции", itemCount: 6 },
    { id: "stations", title: "Практические станции", itemCount: 2 },
  ],
  biochemistry: [
    { id: "course", title: "Курс", itemCount: 22 },
    { id: "controls", title: "Контрольные", itemCount: 4 },
    { id: "credit", title: "Зачёт", itemCount: 1 },
    { id: "exam", title: "Экзамен", itemCount: 1 },
    { id: "ai", title: "VMEDA AI", itemCount: 0 },
  ],
  pharmacology: [
    { id: "course", title: "Курс", itemCount: 18 },
    { id: "controls", title: "Контрольные", itemCount: 3 },
    { id: "credit", title: "Зачёт", itemCount: 1 },
    { id: "exam", title: "Экзамен", itemCount: 1 },
    { id: "ai", title: "VMEDA AI", itemCount: 0 },
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
