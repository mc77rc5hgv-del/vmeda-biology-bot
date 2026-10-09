export const paidSubjectTitles: Record<string, string> = {
  biology: "Биология", physics: "Физика", chemistry: "Химия", anatomy: "Анатомия", histology: "Гистология",
};

export function subscriptionPath(subjectId: string, returnTo: string): string {
  const params = new URLSearchParams({ subject: subjectId, returnTo: subscriptionReturnPath(returnTo) });
  return `/profile/subscriptions?${params}`;
}

export function subscriptionReturnPath(value: string | null): string {
  return value && /^\/(subjects|materials|tests|histology)\/[a-z0-9_/-]+$/.test(value) ? value : "/profile";
}

export function notifySubscriptionRequired(response: Response): void {
  const subjectId = response.headers.get("X-VMEDA-Subscription-Required");
  if (response.status === 403 && subjectId && Object.hasOwn(paidSubjectTitles, subjectId)) {
    window.dispatchEvent(new CustomEvent("vmeda:subscription-required", { detail: { subjectId } }));
  }
}


export function planSubject(options: ReadonlyArray<{id: string}>, choice: string | undefined, requested: string): string | undefined {
  if (!options.length) return undefined; // Bundles must omit subject, never send an empty string.
  return choice ?? options.find(option => option.id === requested)?.id;
}
