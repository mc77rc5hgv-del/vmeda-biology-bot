import { useEffect, useState, useRef } from "react";
import { fetchAuthorizedBlob } from "../lib/apiClient";
import styles from "./AuthenticatedImage.module.css";

interface AuthenticatedImageProps {
  src: string;
  alt: string;
  className?: string;
}

/** Защищённые media-endpoint'ы требуют Bearer-токен, который обычный <img src> не отправляет. */
export function AuthenticatedImage({ src, alt, className }: AuthenticatedImageProps) {
  return <AuthenticatedImageRequest key={src} src={src} alt={alt} className={className} />;
}

function AuthenticatedImageRequest({ src, alt, className }: AuthenticatedImageProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [retry, setRetry] = useState(0);
  const [scale, setScale] = useState(1);
  const modal = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    let active = true;
    let createdUrl: string | null = null;

    fetchAuthorizedBlob(src)
      .then((blob) => {
        if (!active) return;
        createdUrl = URL.createObjectURL(blob);
        setObjectUrl(createdUrl);
      })
      .catch(() => {
        if (active) setFailed(true);
      });

    return () => {
      active = false;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [src, retry]);

  useEffect(() => {
    if (!expanded) return;
    const previousOverflow = document.body.style.overflow;
    const previousFocus = document.activeElement as HTMLElement | null;
    const triggerElement = trigger.current;
    modal.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Tab") {
        const buttons = Array.from(modal.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []);
        const first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus();}
        else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus();}
      }
      if (event.key === "Escape") setExpanded(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      (previousFocus ?? triggerElement)?.focus();
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [expanded]);

  if (failed) return <div className={styles.loadError} role="status">
    <p>Изображение не загрузилось</p>
    <button type="button" onClick={() => { setFailed(false); setObjectUrl(null); setRetry((value) => value + 1); }}>Повторить загрузку</button>
  </div>;
  if (!objectUrl) return <div aria-hidden="true" className={className}>Загрузка изображения…</div>;

  return (
    <>
      <button
        type="button"
        ref={trigger}
        className={styles.zoomTrigger}
        onClick={() => {setScale(1); setExpanded(true);}}
        aria-label={`Открыть изображение «${alt}» в полном размере`}
      >
        <img src={objectUrl} alt={alt} className={className} onError={() => { setFailed(true); setExpanded(false); }} />
        <span className={styles.zoomHint}>Нажмите, чтобы увеличить</span>
      </button>

      {expanded && (
        <div
          ref={modal}
          className={styles.backdrop}
          role="dialog"
          aria-modal="true"
          aria-label={alt}
          onClick={() => setExpanded(false)}
        >
          <button
            type="button"
            className={styles.closeButton}
            onClick={() => setExpanded(false)}
            aria-label="Закрыть изображение"
          >
            ×
          </button>
          <div className={styles.fullImageViewport}>
            <img
              src={objectUrl}
              alt={alt}
              className={styles.fullImage}
              style={{width: `${scale * 100}%`, maxWidth: "none"}}
              onClick={(event) => event.stopPropagation()}
            />
          </div>
          <div className={styles.zoomControls} onClick={event => event.stopPropagation()}>
            <button type="button" disabled={scale <= 1} onClick={() => setScale(value => Math.max(1, value - .5))} aria-label="Уменьшить">−</button>
            <button type="button" onClick={() => setScale(1)} aria-label="Исходный масштаб">{Math.round(scale * 100)}%</button>
            <button type="button" disabled={scale >= 4} onClick={() => setScale(value => Math.min(4, value + .5))} aria-label="Увеличить">+</button>
          </div>
        </div>
      )}
    </>
  );
}
