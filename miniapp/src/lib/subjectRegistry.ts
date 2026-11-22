// Единый реестр предметов Mini App. Без импортов: его читают и браузерный код, и node-тесты
// (tests/subscriptions.mjs транспилирует модули по одному). Новый предмет добавляется здесь;
// subjectIcons.ts типизирован по SubjectId, поэтому забытая иконка ломает сборку, а не экран.
// CSS-оформление предмета (styles/tokens.css, [data-subject="…"]) по-прежнему задаётся отдельно.

interface SubjectMeta {
  title: string;
  /** Суффикс CSS-токена --subject-<accent> из styles/tokens.css. */
  accent: string;
  /** Есть контент-адаптер в web_api (иначе экраны показывают дизайн-заглушку из mockData.ts). */
  realBacked: boolean;
  /** Бэкенд может ответить 403 с X-VMEDA-Subscription-Required для этого предмета. */
  paid: boolean;
  /** Показывается и на 1-м, и на 2-м курсе (общий доступ и прогресс). */
  bothCourses: boolean;
}

export const SUBJECTS = {
  biology: { title: "Биология", accent: "biology", realBacked: true, paid: true, bothCourses: false },
  physics: { title: "Физика", accent: "physics", realBacked: true, paid: true, bothCourses: false },
  chemistry: { title: "Химия", accent: "chemistry", realBacked: true, paid: true, bothCourses: false },
  anatomy: { title: "Анатомия", accent: "anatomy", realBacked: true, paid: true, bothCourses: true },
  histology: { title: "Гистология", accent: "histology", realBacked: true, paid: true, bothCourses: true },
  latin: { title: "Латинский язык", accent: "latin", realBacked: true, paid: false, bothCourses: false },
  law: { title: "Правоведение", accent: "law", realBacked: true, paid: false, bothCourses: false },
  physiology: { title: "Нормальная физиология", accent: "physiology", realBacked: true, paid: false, bothCourses: false },
  operative_surgery: { title: "Оперативная хирургия", accent: "operative-surgery", realBacked: true, paid: false, bothCourses: false },
  biochemistry: { title: "Биохимия", accent: "biochemistry", realBacked: true, paid: false, bothCourses: false },
  pharmacology: { title: "Фармакология", accent: "pharmacology", realBacked: true, paid: false, bothCourses: false },
} satisfies Record<string, SubjectMeta>;

export type SubjectId = keyof typeof SUBJECTS;

export function subjectMeta(subjectId: string): SubjectMeta | undefined {
  return Object.hasOwn(SUBJECTS, subjectId) ? SUBJECTS[subjectId as SubjectId] : undefined;
}

export function subjectIdsWhere(predicate: (meta: SubjectMeta) => boolean): string[] {
  return Object.entries(SUBJECTS).filter(([, meta]) => predicate(meta)).map(([id]) => id);
}
