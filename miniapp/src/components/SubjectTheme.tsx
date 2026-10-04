import type { ReactNode } from "react";

/** Цвета наследуются всеми экранами предмета; оболочка не меняет геометрию. */
export function SubjectTheme({ subjectId, children }: { subjectId?: string; children: ReactNode }) {
  return <div className="subject-theme" data-subject={subjectId}>{children}</div>;
}
