import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Check, ShieldCheck, Sparkles } from "lucide-react";
import { fetchSubscriptionCatalog, createSubscriptionInvoice, fetchSubscriptionPayment, createSbpSubscription, fetchBillingHistory, type SubscriptionPlan } from "../lib/apiClient";
import { useAuthStore, useUiStore } from "../lib/store";
import { canOpenInvoice, openInvoice, openPaymentLink, openTelegramLink, useTelegramBackButton } from "../lib/telegram";
import { StateMessage } from "../components/StateMessage";
import { Skeleton } from "../components/Skeleton";
import styles from "./Subscriptions.module.css";
const date = (value: string) => new Date(value).toLocaleDateString("ru-RU", {day: "numeric", month: "long", year: "numeric"});
const term = (plan: SubscriptionPlan) => plan.duration_days ? `${plan.duration_days} дней` : plan.expires_at ? `до ${date(plan.expires_at)}` : "Без срока окончания";
export function SubscriptionsPage() {
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate("/profile"));
  const userId = useAuthStore(state => state.profile?.userId);
  const authenticated = useAuthStore(state => state.status === "authenticated");
  const selectedCourse = useUiStore(state => state.selectedCourse);
  const [course, setCourse] = useState<number>(selectedCourse);
  const [choices, setChoices] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const storageKey = `vmeda:pending-subscription:${userId}`;
  const [pending, setPending] = useState<string | null>(() => { try { return localStorage.getItem(storageKey); } catch { return null; } });
  const [pendingUrl, setPendingUrl] = useState<string | null>(() => { try { return localStorage.getItem(storageKey + ":url"); } catch { return null; } });
  const mounted = useRef(true);
  const lock = useRef(false);
  const requestKeys = useRef<Record<string, string>>({});
  const client = useQueryClient();
  const catalog = useQuery({queryKey: ["subscriptions", "catalog", userId], queryFn: fetchSubscriptionCatalog, enabled: authenticated});
  const history = useQuery({queryKey: ["subscriptions", "history", userId], queryFn: fetchBillingHistory, enabled: authenticated, refetchInterval: pending ? 15000 : false});
  const receipt = useQuery({queryKey: ["subscriptions", "payment", userId, pending], queryFn: () => fetchSubscriptionPayment(pending!), enabled: authenticated && Boolean(pending), refetchInterval: query => query.state.data?.status === "processing" || !query.state.data ? 2000 : false, retry: 2});
  useEffect(() => {
    mounted.current = true;
    queueMicrotask(() => { if (mounted.current) { try { setPending(localStorage.getItem(storageKey)); setPendingUrl(localStorage.getItem(storageKey + ":url")); } catch { /* Current session still works. */ } } });
    return () => { mounted.current = false; };
  }, [storageKey]);
  const remember = (id: string | null, url?: string) => { try { if (id) { localStorage.setItem(storageKey, id); if (url) localStorage.setItem(storageKey + ":url", url); } else { localStorage.removeItem(storageKey); localStorage.removeItem(storageKey + ":url"); } } catch { /* Poll in this session. */ } if (mounted.current) { setPending(id); if (url || !id) setPendingUrl(url ?? null); } };
  useEffect(() => {
    if (receipt.data?.status === "applied") {
      try { localStorage.removeItem(storageKey); localStorage.removeItem(storageKey + ":url"); } catch { /* No pending payment. */ }
      queueMicrotask(() => { if (mounted.current) { setPending(null); setNotice("Подписка активирована! Доступ обновлён в боте и miniapp."); } });
      for (const key of ["subscription", "subscriptions", "access", "me", "subjects", "subject", "learning", "dashboard"]) void client.invalidateQueries({queryKey: [key]});
    }
  }, [receipt.data?.status, client, storageKey]);
  useEffect(() => {
    if (receipt.data?.status === "failed" || receipt.data?.status === "cancelled") {
      queueMicrotask(() => { if (mounted.current) { setNotice("СБП-счёт отменён или не оплачен. Можно выбрать другой способ. История сохранена."); setPending(null); setPendingUrl(null); } });
      try { localStorage.removeItem(storageKey); localStorage.removeItem(storageKey + ":url"); } catch { /* Session state is cleared. */ }
      void client.invalidateQueries({queryKey: ["subscriptions", "history", userId]});
    }
  }, [receipt.data?.status, storageKey, client, userId]);
  const buy = async (plan: SubscriptionPlan) => {
    if (lock.current || pending) return;
    lock.current = true; setBusy(true); setNotice("");
    try {
      const invoice = await createSubscriptionInvoice(plan.id, choices[plan.id]);
      remember(invoice.payment_id, invoice.url);
      openInvoice(invoice.url, status => {
        lock.current = false; if (mounted.current) setBusy(false);
        if (status === "cancelled" || status === "failed") { remember(null); if (mounted.current) setNotice(status === "cancelled" ? "Оплата отменена. Можно выбрать тариф снова." : "Telegram не подтвердил оплату. Попробуй ещё раз."); }
        else { if (mounted.current) setNotice("Проверяем подтверждение платежа. Доступ появится после обработки ботом."); void client.invalidateQueries({queryKey: ["subscriptions", "payment", userId, invoice.payment_id]}); }
      });
    } catch (error) { remember(null); lock.current = false; if (mounted.current) { setBusy(false); setNotice(error instanceof Error ? error.message : "Не удалось открыть оплату"); } }
  };
  const buySbp = async (plan: SubscriptionPlan) => {
    if (lock.current || pending) return;
    lock.current = true; setBusy(true); setNotice("");
    const key = `vmeda:sbp-request:${userId}:${plan.id}:${choices[plan.id] ?? "all"}`;
    try {
      let requestKey = requestKeys.current[key];
      try { requestKey = localStorage.getItem(key) ?? requestKey; } catch { /* Use session nonce. */ }
      if (!requestKey) { requestKey = crypto.randomUUID(); requestKeys.current[key] = requestKey; try { localStorage.setItem(key, requestKey); } catch { /* Use session nonce. */ } }
      const invoice = await createSbpSubscription(plan.id, requestKey, choices[plan.id]);
      remember(invoice.payment_id, invoice.url);
      delete requestKeys.current[key];
      try { localStorage.removeItem(key); } catch { /* Saved server quote remains available. */ }
      setNotice("Счёт СБП готов. После оплаты вернись сюда — подписка активируется автоматически. Повторно платить не нужно.");
      try { openPaymentLink(invoice.url); } catch { setNotice("Счёт сохранён. Нажми «Продолжить оплату», чтобы открыть СБП."); }
      void history.refetch();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось создать счёт СБП"); }
    finally { lock.current = false; if (mounted.current) setBusy(false); }
  };
  const transfer = (plan: SubscriptionPlan) => {
    const subject = plan.subject_options.find(option => option.id === choices[plan.id]);
    openTelegramLink(`https://t.me/vmeda_helper?text=${encodeURIComponent(`Здравствуйте! Хочу оформить подписку «${plan.title}»${subject ? ` (${subject.title})` : ""} за ${plan.price_rub}₽ в VMEDA. Пришлите реквизиты для перевода на карту.`)}`);
  };
  const support = () => openTelegramLink(`https://t.me/vmeda_helper?text=${encodeURIComponent("Здравствуйте! Нужна помощь с подпиской VMEDA." + (pending ? ` Платёж: ${pending}` : ""))}`);
  return <div className={`screen ${styles.page}`}>
    <button className={styles.back} onClick={() => navigate("/profile")}><ArrowLeft size={18} /> Профиль</button>
    <header className={styles.heading}><span className={styles.eyebrow}><Sparkles size={16} /> VMEDA</span><h1>Подписки</h1><p>Выбери доступ для своего курса и готовься в боте и miniapp.</p></header>
    {!authenticated ? <StateMessage title="Открой miniapp из Telegram" body="Тарифы и оплата доступны после входа через бота." onRetry={() => openTelegramLink("https://t.me/VMEDA_examen_bot")} actionLabel="Открыть бота" /> : catalog.isLoading ? <><Skeleton height={160} radius="22px" /><Skeleton height={250} radius="22px" /></> : catalog.isError || !catalog.data ? <StateMessage title="Не удалось загрузить тарифы" onRetry={() => catalog.refetch()} /> : <>
      <section className={styles.current} aria-label="Текущая подписка"><span className={styles.eyebrow}><ShieldCheck size={18} /> Мой доступ</span><h2>{catalog.data.current.title ?? "Без подписки"}</h2><p>{catalog.data.current.active ? catalog.data.current.expires_at ? `Действует до ${date(catalog.data.current.expires_at)}` : "Без срока окончания" : "Можно выбрать подходящий тариф ниже"}</p><div className={styles.ai}><Sparkles size={18} /><span>AI-запросов осталось: <strong>{catalog.data.current.ai_remaining ?? "без ограничений"}</strong>{catalog.data.current.ai_period === "monthly" ? " в этом месяце" : ""}</span></div>{catalog.data.current.active && <details><summary>Что входит в мою подписку</summary><ul>{catalog.data.current.benefits.map((item, i) => <li key={i}>{item}</li>)}</ul></details>}</section>
      {(notice || pending) && <section className={styles.notice} role="status"><p>{receipt.data?.status === "review" ? "Оплата получена. Твоя текущая подписка сохранена. Обратись в поддержку для проверки платежа." : notice || "Проверяем оплату и активацию подписки…"}</p>{pending && <><button onClick={() => receipt.refetch()}>Проверить статус</button>{pendingUrl && !busy && receipt.data?.status !== "review" && <button disabled={!pending.startsWith("sbp_") && !canOpenInvoice()} onClick={() => { try { if (pending.startsWith("sbp_")) { openPaymentLink(pendingUrl); return; } openInvoice(pendingUrl, status => { if (status === "cancelled" || status === "failed") { remember(null); setNotice(status === "cancelled" ? "Оплата отменена. Можно выбрать тариф снова." : "Telegram не подтвердил оплату. Попробуй ещё раз."); } void receipt.refetch(); }); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось открыть счёт"); } }}>Продолжить оплату</button>}<button onClick={support}>Помощь с оплатой</button>{pending.startsWith("sbp_") && <button onClick={() => { remember(null); setNotice("Счёт сохранён в истории. Если он оплачен, подписка активируется автоматически."); }}>Вернуться к тарифам</button>}{receipt.isError && <small>Не удалось проверить статус. Проверь соединение и повтори.</small>}</>}</section>}
      <div className={styles.tabs} role="group" aria-label="Тарифы по курсу">{[{id: 1, title: "1 курс"}, {id: 2, title: "2 курс"}, {id: 0, title: "Все тарифы"}].map(item => <button key={item.id} aria-pressed={course === item.id} onClick={() => setCourse(item.id)}>{item.title}</button>)}</div>
      <div className={styles.plans}>{catalog.data.plans.filter(plan => !course || plan.courses.includes(course)).map(plan => {
        const current = catalog.data.current.tier_id === plan.id;
        const choice = plan.subject_options.find(option => option.id === choices[plan.id]);
        const reason = plan.unavailable_reason || choice?.unavailable_reason;
        const missingChoice = plan.subject_options.length > 0 && !choice;
        return <article key={plan.id} className={`${styles.plan} ${current ? styles.active : ""}`}>
          <div className={styles.planTop}><span>{current ? "Текущий тариф" : plan.badge || "VMEDA"}</span><span>{term(plan)}</span></div><h2>{plan.title}</h2><div className={styles.price}><strong>{plan.price_rub} ₽</strong><span>или {plan.price_stars} Telegram Stars</span></div><p className={styles.caption}>Разовая оплата · без автоматических списаний</p>
          <ul className={styles.benefits}>{plan.benefits.map((benefit, i) => <li key={i}><Check size={16} /><span>{benefit}</span></li>)}</ul>
          {plan.subject_options.length > 0 && <label className={styles.choice}>Выбери предмет<select value={choices[plan.id] ?? ""} onChange={event => setChoices({...choices, [plan.id]: event.target.value})}><option value="" disabled>Выбрать предмет</option>{plan.subject_options.map(option => <option key={option.id} value={option.id} disabled={Boolean(option.unavailable_reason)}>{option.title}</option>)}</select></label>}
          <div className={styles.purchase}>{catalog.data.sbp_available && <button disabled={busy || Boolean(pending) || Boolean(reason) || missingChoice} onClick={() => void buySbp(plan)}>{current && plan.duration_days ? "Продлить" : "Оплатить"} по СБП · {plan.price_rub} ₽</button>}<button className={styles.secondary} disabled={busy || Boolean(pending) || Boolean(reason) || missingChoice || !canOpenInvoice()} onClick={() => void buy(plan)}>{current && plan.duration_days ? "Продлить" : current ? "Уже активен" : `Оформить за ${plan.price_stars} Stars`}</button><button className={styles.secondary} disabled={busy || Boolean(reason) || missingChoice} onClick={() => transfer(plan)}>Перевод на карту · {plan.price_rub} ₽</button>{reason && <small>{reason}</small>}{!canOpenInvoice() && <small>Для оплаты Stars нужен актуальный Telegram. СБП и перевод на карту доступны отдельно.</small>}</div>
        </article>;
      })}</div>
      {history.data && history.data.payments.length > 0 && <section className={styles.current}><h2>Мои платежи СБП</h2><p>Счета из бота и miniapp в одной истории.</p><div className={styles.history}>{history.data.payments.map(item => <article key={item.id}><div><strong>{catalog.data.plans.find(plan => plan.id === item.tier_id)?.short ?? "Подписка VMEDA"}</strong><small>{new Date(item.created * 1000).toLocaleDateString("ru-RU")} · {item.amount_minor / 100} ₽</small><span>{item.state === "applied" ? "Оплачено · подписка активирована" : item.state === "review" ? "Оплачено · проверка поддержки" : item.state === "creation_unknown" ? "Счёт требует проверки поддержки" : item.state === "failed" || item.state === "cancelled" ? "Счёт не оплачен или отменён" : "Ожидает оплаты"}</span><small className={styles.paymentId}>{item.id}</small></div>{!["applied", "review", "creation_unknown", "failed", "cancelled"].includes(item.state) && <button onClick={() => { remember(item.id, item.url ?? undefined); setNotice("Проверяем сохранённый счёт СБП."); void receipt.refetch(); }}>Проверить</button>}</article>)}</div></section>}
      <footer className={styles.footer}><ShieldCheck size={20} /><p>СБП подтверждает codeePay, оплату Stars — Telegram. Перевод на карту подтверждается вручную. Подписка общая для бота и miniapp. Продление добавляет срок к уже оплаченному периоду.</p><button onClick={support}>Помощь с подпиской</button></footer>
    </>}
  </div>;
}
