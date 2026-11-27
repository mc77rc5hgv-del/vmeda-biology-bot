import { SUBJECTS } from "./subjectRegistry";

export const paidSubjectTitles: Record<string, string> = Object.fromEntries(
  Object.entries(SUBJECTS).filter(([, meta]) => meta.paid).map(([id, meta]) => [id, meta.title]),
);
paidSubjectTitles.anatomy_tests = "Тесты по анатомии";

export function subscriptionPath(subjectId: string, returnTo: string, offerId?: number): string {
  const params = new URLSearchParams({ subject: subjectId, returnTo: subscriptionReturnPath(returnTo) });
  if (offerId !== undefined) params.set("plan", String(offerId));
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

export function normalizePaymentLink(value: string): string {
  let target: URL;
  try { target = new URL(value); }
  catch { throw new Error("Некорректная ссылка оплаты"); }
  const allowed = target.hostname === "payment.codeepay.xyz" || target.hostname === "codeepay.xyz" || target.hostname === "codeepay.ru";
  if (target.protocol !== "https:" || !allowed || target.username || target.password
      || (!target.pathname.startsWith("/payment/") && !target.pathname.startsWith("/transfer/"))) {
    throw new Error("Некорректная ссылка оплаты");
  }
  if (target.hostname === "codeepay.xyz") target.hostname = "payment.codeepay.xyz";
  return target.toString();
}
