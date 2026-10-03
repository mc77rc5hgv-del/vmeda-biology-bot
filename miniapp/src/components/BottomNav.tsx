import { Home, Sparkles, TrendingUp, User } from "lucide-react";
import { NavLink } from "react-router-dom";
import { hapticSelection } from "../lib/telegram";
import { Icon } from "./Icon";
import styles from "./BottomNav.module.css";

const ITEMS = [
  { to: "/", label: "Главная", icon: Home, end: true },
  { to: "/progress", label: "Прогресс", icon: TrendingUp, end: false },
  { to: "/ai", label: "AI", icon: Sparkles, end: false },
  { to: "/profile", label: "Профиль", icon: User, end: false },
];

/** Постоянная нижняя навигация — 4 верхнеуровневые точки входа. Экраны "глубже" (предмет →
 * раздел → материал, тест) не в этом списке — туда ведёт системная кнопка "Назад" Telegram
 * (см. lib/telegram.ts useTelegramBackButton), не таб-бар. */
export function BottomNav() {
  return (
    <nav className={styles.nav} aria-label="Основная навигация">
      {ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => [styles.item, isActive ? styles.itemActive : ""].join(" ")}
          onClick={hapticSelection}
        >
          <Icon icon={item.icon} size={22} />
          <span className={styles.label}>{item.label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
