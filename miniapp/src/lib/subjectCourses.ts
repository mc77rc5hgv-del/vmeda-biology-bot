import type { CourseId, SubjectSummary } from "./types";

const twoYearSubjects = new Set(["anatomy", "histology"]);

/** Both course views open the same subject, access rules and saved progress. */
export function isSubjectOnCourse(subject: Pick<SubjectSummary, "id" | "course">, course: CourseId): boolean {
  return subject.course === course || twoYearSubjects.has(subject.id);
}
