import type { CourseId, SubjectSummary } from "./types";
import { subjectMeta } from "./subjectRegistry";

/** Both course views open the same subject, access rules and saved progress. */
export function isSubjectOnCourse(subject: Pick<SubjectSummary, "id" | "course">, course: CourseId): boolean {
  return subject.course === course || Boolean(subjectMeta(subject.id)?.bothCourses);
}
