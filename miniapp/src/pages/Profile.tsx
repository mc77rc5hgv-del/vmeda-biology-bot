import { ChevronRight, Flame, Target, Users, Zap } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchDashboard, fetchMe, fetchSubscriptionSummary } from "../lib/api";
import { hapticImpact, openTelegramLink, useTelegramBackButton } from "../lib/telegram";
import { Card, PressableCard } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./Profile.module.css";

function initials(firstName: string, lastName: string | null): string {
  return ((firstName?.[0] ?? "") + (lastName?.[0] ?? "")).toUpperCase() || "?";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
}

export function ProfilePage() {
  useTelegramBackButton(null);
  const navigate = useNavigate();
  const meQuery = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const dashboardQuery = useQuery({ queryKey: ["dashboard"], queryFn: fetchDashboard });
  const subQuery = useQuery({ queryKey: ["subscription-summary"], queryFn: fetchSubscriptionSummary });

  if (meQuery.isLoading) {
    return <div className="screen"><Skeleton height={172} radius="22px" /><div className={styles.statsGrid}>{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} height={118} radius="16px" />)}</div></div>;
  }
  if (meQuery.isError || !meQuery.data) {
    return <div className="screen"><StateMessage title="Не удалось загрузить профиль" body="Проверь соединение и попробуй ещё раз." onRetry={() => meQuery.refetch()} /></div>;
  }

  const user = meQuery.data;
  const dashboard = dashboardQuery.data;
  const openBot = () => {
    hapticImpact();
    openTelegramLink("https://t.me/VMEDA_examen_bot");
  };
  const openSupport = () => {
    hapticImpact();
    const text = encodeURIComponent("Здравствуйте! Нужна помощь с VMEDA Mini App.");
    openTelegramLink("https://t.me/vmeda_helper?text=" + text);
  };

  return (
    <div className="screen">
      <div className={styles.hero}>
        {user.photoUrl ? <img className={styles.avatarImage} src={user.photoUrl} alt="" /> : <div className={styles.avatar}>{initials(user.firstName, user.lastName)}</div>}
        <div className={styles.name}>{user.firstName} {user.lastName ?? ""}</div>
        {user.username && <div className={styles.username}>@{user.username}</div>}
      </div>

      {dashboardQuery.isLoading ? (
        <div className={styles.statsGrid}>{Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} height={118} radius="16px" />)}</div>
      ) : dashboardQuery.isError || !dashboard ? (
        <Card className={styles.queryError}><span>Не удалось загрузить статистику</span><button type="button" onClick={() => dashboardQuery.refetch()}>Повторить</button></Card>
      ) : (
        <div className={styles.statsGrid}>
          <PressableCard className={[styles.statCard, styles.statButton].join(" ")} onClick={() => navigate("/progress")} aria-label="Открыть прогресс и серию">
            <Icon icon={Flame} size={18} color="var(--amber)" /><span className={styles.statValue}>{dashboard.streakDays} дн.</span><span className={styles.statLabel}>Серия</span>
          </PressableCard>
          <PressableCard className={[styles.statCard, styles.statButton].join(" ")} onClick={() => navigate("/progress")} aria-label="Открыть прогресс XP">
            <Icon icon={Zap} size={18} color="var(--academic-blue)" /><span className={styles.statValue}>{dashboard.xp}</span><span className={styles.statLabel}>XP</span>
          </PressableCard>
          <PressableCard className={[styles.statCard, styles.statButton].join(" ")} onClick={() => navigate("/progress")} aria-label="Открыть готовность">
            <Icon icon={Target} size={18} color="var(--muted-teal)" /><span className={styles.statValue}>{dashboard.readinessPercent}%</span><span className={styles.statLabel}>Готовность</span>
          </PressableCard>
          <PressableCard className={[styles.statCard, styles.statButton].join(" ")} onClick={() => navigate("/profile/referrals")} aria-label="Открыть реферальную программу">
            <Icon icon={Users} size={18} color="var(--academy-red)" /><span className={styles.statValue}>{user.referralCountThisMonth}</span><span className={styles.statLabel}>Рефералов в этом месяце</span>
          </PressableCard>
        </div>
      )}

      <PressableCard className={styles.subCard} onClick={openBot} aria-label="Открыть управление подпиской в боте">
        <div className={styles.subRow}>
          <div>
            <div className={styles.subTitle}>{subQuery.isLoading ? "Проверяем подписку…" : subQuery.isError ? "Не удалось проверить подписку" : subQuery.data?.subscriptionTitle ?? "Нет активной подписки"}</div>
            {subQuery.data?.subscriptionExpiresAt && <div className={styles.subMeta}>до {formatDate(subQuery.data.subscriptionExpiresAt)}</div>}
            {!subQuery.isLoading && !subQuery.isError && <div className={styles.subMeta}>AI-запросов осталось: {subQuery.data?.aiRequestsLeft ?? "без ограничений"}</div>}
          </div>
          <span className={styles.subAction}>{subQuery.data?.subscriptionTitle ? "Управлять" : "Оформить"}</span>
        </div>
      </PressableCard>

      <PressableCard className={styles.linkRow} onClick={() => navigate("/profile/referrals")}><span>Реферальная программа</span><Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" /></PressableCard>
      <PressableCard className={styles.linkRow} onClick={() => navigate("/profile/favorites")}><span>Избранное</span><Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" /></PressableCard>
      <PressableCard className={styles.linkRow} onClick={openSupport}><span>Поддержка</span><Icon icon={ChevronRight} size={18} color="var(--ink-secondary)" /></PressableCard>
    </div>
  );
}
