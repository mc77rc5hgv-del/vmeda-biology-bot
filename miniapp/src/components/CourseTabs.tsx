import type { CourseId } from "../lib/types";
import { hapticSelection } from "../lib/telegram";
import styles from "./CourseTabs.module.css";

interface CourseTabsProps {
  value: CourseId;
  onChange: (course: CourseId) => void;
}

export function CourseTabs({ value, onChange }: CourseTabsProps) {
  return (
    <div className={styles.tabs} role="tablist" aria-label="Курс">
      {([1, 2] as CourseId[]).map((course) => (
        <button
          key={course}
          type="button"
          role="tab"
          aria-selected={value === course}
          className={[styles.tab, value === course ? styles.tabActive : ""].join(" ")}
          onClick={() => {
            hapticSelection();
            onChange(course);
          }}
        >
          <span className={styles.number}>{course}</span> курс
        </button>
      ))}
    </div>
  );
}
