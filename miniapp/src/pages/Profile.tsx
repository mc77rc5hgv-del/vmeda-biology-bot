import { ChevronRight, Flame, Target, Users, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchDashboard, fetchMe, fetchSubscriptionSummary } from "../lib/api";
import { useTelegramBackButton } from "../lib/telegram";
import { Card, PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import styles from "./Profile.module.css";

function initials(firstName: string, lastName: string | null): string {
  return ((firstName?.[0] ?? "") + (lastName?.[0] ?? "")).toUpperCase() || "?";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export function ProfilePage() {
  useTelegramBackButton(null); // раздел нижней навигации

  const meQuery = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const dashboardQuery = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard });
  const subQuery = useQuery({ queryKey: ["subscription-summary"], queryFn: fetchSubscriptionSummary });

  if (meQuery.isLoading || !meQuery.data) {
    return (
      <div className="screen">
        <Skeleton height={140} radius="22px" />
        <Skeleton height={80} radius="16px" />
      </div>
    );
  }

  const user = meQuery.data;

  return (
    <div className="screen">
      <div className={styles.hero}>
        <div className={styles.avatar}>{initials(user.firstName, user.lastName)}</div>
        <div className={styles.name}>
          {user.firstName} {user.lastName ?? ""}
        </div>
        {user.username && <div className={styles.username}>@{user.username}</div>}
      </div>

      {dashboardQuery.data && (
        <div className={styles.statsGrid}>
          <Card className={styles.statCard}>
            <Icon icon={Flame} size={18} color="var(--amber)" />
            <span className={styles.statValue}>{dashboardQuery.data.streakDays} дн.</span>
            <span className={styles.statLabel}>Серия</span>
          </Card>
          <Card className={styles.statCard}>
            <Icon icon={Zap} size={18} color="var(--academic-blue)" />
            <span className={styles.statValue}>{dashboardQuery.data.xp}</span>
            <span className={styles.statLabel}>XP</span>
          </Card>
          <Card className={styles.statCard}>
            <Icon icon={Target} size={18} color="var(--muted-teal)" />
            <span className={styles.statValue}>{dashboardQuery.data.readinessPercent}%</span>
            <span className={styles.statLabel}>Готовность</span>
          </Card>
          <Card className={styles.statCard}>
            <Icon icon={Users} size={18} color="var(--academy-red)" />
            <span className={styles.statValue}>{user.referralCountThisMonth}</span>
            <span className={styles.statLabel}>Рефералов в этом месяце</span>
          </Card>
        </div>
      )}

      <Card>
        <div className={styles.subRow}>
          <div>
            <div className={styles.subTitle}>
              {subQuery.isError
                ? "Не удалось проверить подписку"
                : subQuery.data?.subscriptionTitle ?? "Нет активной подписки"}
            </div>
            {subQuery.data?.subscriptionExpiresAt && (
              <div className={styles.subMeta}>до {formatDate(subQuery.data.subscriptionExpiresAt)}</div>
            )}
            {subQuery.data && (
              <div className={styles.subMeta}>
                AI-запросов осталось: {subQuery.data.aiRequestsLeft ?? "—"}
              </div>
            )}
          </div>
        </div>
      </Card>

      <PressableCard className={styles.linkRow}>
        <span>Реферальная программа</span>
        <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
      </PressableCard>
      <PressableCard className={styles.linkRow}>
        <span>Избранное</span>
        <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
      </PressableCard>
      <PressableCard className={styles.linkRow}>
        <span>Поддержка</span>
        <Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" />
      </PressableCard>
    </div>
  );
}
