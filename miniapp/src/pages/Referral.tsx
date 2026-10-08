import { Copy, Gift, Share2, Users } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { fetchMe } from "../lib/api";
import { hapticImpact, openTelegramLink, useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./ProfileDetails.module.css";

const MONTHLY_TARGET = 2;

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

export function ReferralPage() {
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate("/profile"));
  const meQuery = useQuery({ queryKey: ["me"], queryFn: fetchMe });
  const [copied, setCopied] = useState(false);

  if (meQuery.isLoading) return <div className="screen"><Skeleton height={62} width="72%" /><Skeleton height={120} radius="18px" /><Skeleton height={78} radius="18px" /></div>;
  if (meQuery.isError || !meQuery.data) return <div className="screen"><StateMessage title="Не удалось загрузить реферальную программу" onRetry={() => meQuery.refetch()} /></div>;

  const user = meQuery.data;
  const inviteLink = "https://t.me/VMEDA_examen_bot?start=ref_" + user.id;
  const monthly = user.referralCountThisMonth;
  const progress = Math.min(100, Math.round((monthly / MONTHLY_TARGET) * 100));

  const handleCopy = async () => {
    try {
      await copyText(inviteLink);
      hapticImpact("light");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      openTelegramLink(inviteLink);
    }
  };
  const handleShare = () => {
    hapticImpact();
    const text = "Готовься к занятиям и экзаменам вместе с VMEDA BOT + AI";
    openTelegramLink("https://t.me/share/url?url=" + encodeURIComponent(inviteLink) + "&text=" + encodeURIComponent(text));
  };

  return (
    <div className="screen">
      <header className={styles.intro}><h1 className={styles.title}>Реферальная программа</h1><p className={styles.subtitle}>Приглашай однокурсников и открывай доступ к учебным разделам.</p></header>
      <div className={styles.stats}>
        <Card className={styles.stat}><Icon icon={Users} size={20} color="var(--academy-red)" /><strong>{monthly}</strong><span>в этом месяце</span></Card>
        <Card className={styles.stat}><Icon icon={Gift} size={20} color="var(--amber)" /><strong>{user.referralCount}</strong><span>за всё время</span></Card>
      </div>
      <Card>
        <strong>До полного доступа: {Math.max(0, MONTHLY_TARGET - monthly)}</strong>
        <div className={styles.progressTrack} style={{ marginTop: 12 }}><div className={styles.progressFill} style={{ width: progress + "%" }} /></div>
        <p className={styles.note} style={{ marginTop: 10 }}>Для доступа по реферальной программе нужно {MONTHLY_TARGET} новых пользователя в текущем календарном месяце.</p>
      </Card>
      <Card><div className={styles.linkBox}><span className={styles.linkText}>{inviteLink}</span><button type="button" className={styles.copyButton} onClick={handleCopy}><Icon icon={Copy} size={17} /> {copied ? "Скопировано" : "Копировать"}</button></div></Card>
      <button type="button" className={styles.primaryButton} onClick={handleShare}><Icon icon={Share2} size={18} /> Поделиться ссылкой</button>
    </div>
  );
}
