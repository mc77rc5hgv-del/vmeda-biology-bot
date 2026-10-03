import { useEffect, useState } from "react";
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
  }, [src]);

  useEffect(() => {
    if (!expanded) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [expanded]);

  if (failed) return <div role="img" aria-label={alt} className={className}>Изображение недоступно</div>;
  if (!objectUrl) return <div aria-hidden="true" className={className}>Загрузка изображения…</div>;

  return (
    <>
      <button
        type="button"
        className={styles.zoomTrigger}
        onClick={() => setExpanded(true)}
        aria-label={`Открыть изображение «${alt}» в полном размере`}
      >
        <img src={objectUrl} alt={alt} className={className} />
        <span className={styles.zoomHint}>Нажмите, чтобы увеличить</span>
      </button>

      {expanded && (
        <div
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
              onClick={(event) => event.stopPropagation()}
            />
          </div>
          <span className={styles.fullImageHint}>Можно увеличивать жестом</span>
        </div>
      )}
    </>
  );
}
