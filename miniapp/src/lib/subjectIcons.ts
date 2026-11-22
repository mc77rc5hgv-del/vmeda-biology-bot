import { Activity, Atom, Bone, Dna, FlaskConical, Landmark, Microscope, Pill, Scale, Scissors } from "lucide-react";
import { subjectMeta, type SubjectId } from "./subjectRegistry";

const icons: Record<SubjectId, typeof Activity> = {
  physiology: Activity, operative_surgery: Scissors, biochemistry: Atom,
  pharmacology: Pill, biology: Dna, physics: Atom, chemistry: FlaskConical,
  anatomy: Bone, histology: Microscope, latin: Landmark, law: Scale,
};

/** Общие значки главной страницы и прогресса. */
export function subjectIcon(subjectId: string) { return subjectMeta(subjectId) ? icons[subjectId as SubjectId] : Dna; }
