import { useEffect, useRef } from "react";
import { PressableCard } from "./Card";

interface LoadMoreProps {
  remaining: number;
  onMore: () => void;
  className?: string;
  titleClassName?: string;
}

/** Догружает следующую порцию списка сама, когда пользователь докручивает почти до конца;
 * кнопка остаётся для клавиатуры, скринридеров и WebView без IntersectionObserver. */
export function LoadMore({ remaining, onMore, className, titleClassName }: LoadMoreProps) {
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onMore();
    }, { rootMargin: "0px 0px 600px 0px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [onMore, remaining]);
  return (
    <div ref={sentinel}>
      <PressableCard className={className} onClick={onMore}>
        <span className={titleClassName}>Показать ещё ({remaining})</span>
      </PressableCard>
    </div>
  );
}
