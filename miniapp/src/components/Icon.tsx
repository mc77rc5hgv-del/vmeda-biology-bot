import type { LucideIcon } from "lucide-react";

interface IconProps {
  icon: LucideIcon;
  size?: number;
  color?: string;
  label?: string;
}

/** Единая обёртка над lucide-react — см. §6 ТЗ: "не использовать emoji как основные иконки
 * интерфейса". Любая иконка в UI идёт через этот компонент, а не напрямую через lucide, чтобы
 * default-размер/strokeWidth были одинаковыми везде без повторения пропсов. `label` делает
 * декоративную по умолчанию SVG-иконку доступной (aria-label) там, где она не сопровождается
 * видимым текстом — см. §18 ТЗ "подписи для иконок". */
export function Icon({ icon: LucideIconComponent, size = 20, color, label }: IconProps) {
  return (
    <LucideIconComponent
      size={size}
      color={color ?? "currentColor"}
      strokeWidth={2}
      aria-hidden={label ? undefined : true}
      role={label ? "img" : undefined}
      aria-label={label}
    />
  );
}
