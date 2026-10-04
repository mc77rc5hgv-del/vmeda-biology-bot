import type { ReactNode } from "react";

/** Цвета наследуются всеми экранами предмета; оболочка не меняет геометрию. */
export function SubjectTheme({ subjectId, children, appShell = false }: { subjectId?: string; children: ReactNode; appShell?: boolean }) {
  return <div className={appShell ? "subject-theme app-shell" : "subject-theme"} data-subject={subjectId}>{children}</div>;
}
