import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Flame, Gem } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { fetchDashboard, fetchSubscriptionSummary } from "../lib/api";
import { formatDayCount } from "../lib/format";
import { Icon } from "./Icon";
import styles from "./HomeReminders.module.css";

const EXPIRY_WARNING_DAYS = 3;
const DAY_MS = 86_400_000;

/** Ненавязчивые напоминания на главной: продлить серию сегодня и продлить подписку заранее.
 * Используют те же ключи запросов, что и профиль, поэтому лишних запросов не создают. */
export function HomeReminders() {
  const navigate = useNavigate();
  const [now] = useState(() => Date.now());
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard }).data;
  const access = useQuery({ queryKey: ["subscription", "summary"], queryFn: fetchSubscriptionSummary }).data;

  const expiresAt = access?.subscriptionExpiresAt ? Date.parse(access.subscriptionExpiresAt) : NaN;
  const daysLeft = Number.isFinite(expiresAt) ? Math.ceil((expiresAt - now) / DAY_MS) : null;
  const subscriptionEnding = daysLeft !== null && daysLeft > 0 && daysLeft <= EXPIRY_WARNING_DAYS;
  // studiedToday отсутствует у старого бэкенда — тогда напоминание о серии не показываем.
  const streakAtRisk = dashboard?.studiedToday === false && dashboard.streakDays > 0;

  if (!subscriptionEnding && !streakAtRisk) return null;
  return (
    <div className={styles.stack}>
      {streakAtRisk && (
        <div className={styles.reminder} role="status">
          <span className={styles.icon} style={{ color: "var(--amber)" }}><Icon icon={Flame} size={20} /></span>
          <p>Серия {formatDayCount(dashboard.streakDays)} — открой любой материал сегодня, чтобы её не потерять.</p>
        </div>
      )}
      {subscriptionEnding && (
        <div className={styles.reminder} role="status">
          <span className={styles.icon} style={{ color: "var(--academic-blue)" }}><Icon icon={Gem} size={20} /></span>
          <p>
            <strong>Подписка закончится {daysLeft === 1 ? "завтра" : `через ${formatDayCount(daysLeft)}`}</strong>
            {access?.subscriptionTitle && <span>{access.subscriptionTitle}</span>}
          </p>
          <button type="button" onClick={() => navigate("/profile/subscriptions")}>Продлить</button>
        </div>
      )}
    </div>
  );
}
