import { useEffect, useState } from "react";
import { fetchAuthorizedBlob } from "../lib/apiClient";

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

  if (failed) return <div role="img" aria-label={alt} className={className}>Изображение недоступно</div>;
  if (!objectUrl) return <div aria-hidden="true" className={className}>Загрузка изображения…</div>;
  return <img src={objectUrl} alt={alt} className={className} />;
}
