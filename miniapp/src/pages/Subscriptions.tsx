import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Check, ShieldCheck, Sparkles, Star } from "lucide-react";
import { fetchSubscriptionCatalog, createSubscriptionInvoice, fetchSubscriptionPayment, type SubscriptionPlan } from "../lib/apiClient";
import { useAuthStore, useUiStore } from "../lib/store";
import { canOpenInvoice, openInvoice, openTelegramLink, useTelegramBackButton } from "../lib/telegram";
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
  const client = useQueryClient();
  const catalog = useQuery({queryKey: ["subscriptions", "catalog", userId], queryFn: fetchSubscriptionCatalog, enabled: authenticated});
  const receipt = useQuery({queryKey: ["subscriptions", "payment", userId, pending], queryFn: () => fetchSubscriptionPayment(pending!), enabled: authenticated && Boolean(pending), refetchInterval: query => query.state.data?.status === "processing" || !query.state.data ? 2000 : false, retry: 2});
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, [storageKey]);
  const remember = (id: string | null, url?: string) => { try { if (id) { localStorage.setItem(storageKey, id); if (url) localStorage.setItem(storageKey + ":url", url); } else { localStorage.removeItem(storageKey); localStorage.removeItem(storageKey + ":url"); } } catch { /* Poll in this session. */ } if (mounted.current) { setPending(id); if (url || !id) setPendingUrl(url ?? null); } };
  useEffect(() => {
    if (receipt.data?.status === "applied") {
      try { localStorage.removeItem(storageKey); localStorage.removeItem(storageKey + ":url"); } catch { /* No pending payment. */ }
      queueMicrotask(() => { if (mounted.current) { setPending(null); setNotice("Подписка активирована! Доступ обновлён в боте и miniapp."); } });
      for (const key of ["subscription", "subscriptions", "access", "me", "subjects", "subject", "learning", "dashboard"]) void client.invalidateQueries({queryKey: [key]});
    }
  }, [receipt.data?.status, client, storageKey]);
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
  const support = () => openTelegramLink(`https://t.me/vmeda_helper?text=${encodeURIComponent("Здравствуйте! Нужна помощь с подпиской VMEDA." + (pending ? ` Платёж: ${pending}` : ""))}`);
  return <div className={`screen ${styles.page}`}>
    <button className={styles.back} onClick={() => navigate("/profile")}><ArrowLeft size={18} /> Профиль</button>
    <header className={styles.heading}><span className={styles.eyebrow}><Sparkles size={16} /> VMEDA</span><h1>Подписки</h1><p>Выбери доступ для своего курса и готовься в боте и miniapp.</p></header>
    {!authenticated ? <StateMessage title="Открой miniapp из Telegram" body="Тарифы и оплата доступны после входа через бота." onRetry={() => openTelegramLink("https://t.me/VMEDA_examen_bot")} actionLabel="Открыть бота" /> : catalog.isLoading ? <><Skeleton height={160} radius="22px" /><Skeleton height={250} radius="22px" /></> : catalog.isError || !catalog.data ? <StateMessage title="Не удалось загрузить тарифы" onRetry={() => catalog.refetch()} /> : <>
      <section className={styles.current} aria-label="Текущая подписка"><span className={styles.eyebrow}><ShieldCheck size={18} /> Мой доступ</span><h2>{catalog.data.current.title ?? "Без подписки"}</h2><p>{catalog.data.current.active ? catalog.data.current.expires_at ? `Действует до ${date(catalog.data.current.expires_at)}` : "Без срока окончания" : "Можно выбрать подходящий тариф ниже"}</p><div className={styles.ai}><Sparkles size={18} /><span>AI-запросов осталось: <strong>{catalog.data.current.ai_remaining ?? "без ограничений"}</strong>{catalog.data.current.ai_period === "monthly" ? " в этом месяце" : ""}</span></div>{catalog.data.current.active && <details><summary>Что входит в мою подписку</summary><ul>{catalog.data.current.benefits.map((item, i) => <li key={i}>{item}</li>)}</ul></details>}</section>
      {(notice || pending) && <section className={styles.notice} role="status"><p>{receipt.data?.status === "review" ? "Оплата получена. Твоя текущая подписка сохранена. Обратись в поддержку для проверки платежа." : notice || "Проверяем оплату и активацию подписки…"}</p>{pending && <><button onClick={() => receipt.refetch()}>Проверить статус</button>{pendingUrl && !busy && receipt.data?.status !== "review" && <button disabled={!canOpenInvoice()} onClick={() => { try { openInvoice(pendingUrl, status => { if (status === "cancelled" || status === "failed") remember(null); void receipt.refetch(); }); } catch (error) { setNotice(error instanceof Error ? error.message : "Не удалось открыть счёт"); } }}>Продолжить оплату</button>}<button onClick={support}>Помощь с оплатой</button>{receipt.isError && <small>Не удалось проверить статус. Проверь соединение и повтори.</small>}</>}</section>}
      <div className={styles.tabs} role="group" aria-label="Тарифы по курсу">{[{id: 1, title: "1 курс"}, {id: 2, title: "2 курс"}, {id: 0, title: "Все тарифы"}].map(item => <button key={item.id} aria-pressed={course === item.id} onClick={() => setCourse(item.id)}>{item.title}</button>)}</div>
      <div className={styles.plans}>{catalog.data.plans.filter(plan => !course || plan.courses.includes(course)).map(plan => {
        const current = catalog.data.current.tier_id === plan.id;
        const choice = plan.subject_options.find(option => option.id === choices[plan.id]);
        const reason = plan.unavailable_reason || choice?.unavailable_reason;
        const missingChoice = plan.subject_options.length > 0 && !choice;
        return <article key={plan.id} className={`${styles.plan} ${current ? styles.active : ""}`}>
          <div className={styles.planTop}><span>{current ? "Текущий тариф" : plan.badge || "VMEDA"}</span><span>{term(plan)}</span></div><h2>{plan.title}</h2><div className={styles.price}><Star size={24} /><strong>{plan.price_stars}</strong><span>Telegram Stars</span></div><p className={styles.caption}>Разовая оплата · без автоматических списаний</p>
          <ul className={styles.benefits}>{plan.benefits.map((benefit, i) => <li key={i}><Check size={16} /><span>{benefit}</span></li>)}</ul>
          {plan.subject_options.length > 0 && <label className={styles.choice}>Выбери предмет<select value={choices[plan.id] ?? ""} onChange={event => setChoices({...choices, [plan.id]: event.target.value})}><option value="" disabled>Выбрать предмет</option>{plan.subject_options.map(option => <option key={option.id} value={option.id} disabled={Boolean(option.unavailable_reason)}>{option.title}</option>)}</select></label>}
          <div className={styles.purchase}><button disabled={busy || Boolean(pending) || Boolean(reason) || missingChoice || !canOpenInvoice()} onClick={() => void buy(plan)}>{current && plan.duration_days ? "Продлить" : current ? "Уже активен" : `Оформить за ${plan.price_stars} Stars`}</button>{reason && <small>{reason}</small>}{!canOpenInvoice() && <small>Для оплаты нужен актуальный Telegram.</small>}</div>
        </article>;
      })}</div>
      <footer className={styles.footer}><ShieldCheck size={20} /><p>Telegram подтверждает оплату. Подписка общая для бота и miniapp. Продление добавляет срок к уже оплаченному периоду.</p><button onClick={support}>Помощь с подпиской</button></footer>
    </>}
  </div>;
}
