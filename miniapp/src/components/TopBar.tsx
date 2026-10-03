import { useNavigate } from "react-router-dom";
import type { UserProfile } from "../lib/types";
import styles from "./TopBar.module.css";

interface TopBarProps {
  user: UserProfile;
}

function initials(user: UserProfile): string {
  const first = user.firstName?.[0] ?? "";
  const last = user.lastName?.[0] ?? "";
  return (first + last).toUpperCase() || "?";
}

/** Верхняя панель главного экрана — см. §8 ТЗ: бренд-блок слева ("VMEDA / Военно-медицинская
 * академия / СПБ · 1798"), фото/инициалы пользователя справа как вход в профиль. */
export function TopBar({ user }: TopBarProps) {
  const navigate = useNavigate();
  return (
    <div className={styles.bar}>
      <div className={styles.brand}>
        <span className={styles.wordmark}>VMEDA</span>
        <span className={styles.subtitle}>
          Военно-медицинская академия
          <br />
          СПБ · 1798
        </span>
      </div>
      <button
        type="button"
        className={styles.avatarButton}
        onClick={() => navigate("/profile")}
        aria-label="Профиль"
      >
        {user.photoUrl ? (
          <img className={styles.avatarImg} src={user.photoUrl} alt="" />
        ) : (
          <span className={styles.avatarInitials}>{initials(user)}</span>
        )}
      </button>
    </div>
  );
}
