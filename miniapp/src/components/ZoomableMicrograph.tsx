import { LocateFixed, Maximize2, Minimize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fetchAuthorizedBlob } from "../lib/apiClient";
import type { HistologyMarker } from "../lib/types";
import { Icon } from "./Icon";
import styles from "./ZoomableMicrograph.module.css";

interface Props {
  src: string;
  alt: string;
  markers?: HistologyMarker[];
}

export function ZoomableMicrograph({ src, alt, markers = [] }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [showMarkers, setShowMarkers] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const dragging = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const pinching = useRef<{ distance: number; scale: number } | null>(null);

  useEffect(() => {
    let active = true;
    let url: string | null = null;
    fetchAuthorizedBlob(src)
      .then((blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setObjectUrl(url);
      })
      .catch(() => active && setFailed(true));
    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [src]);

  useEffect(() => {
    if (!fullscreen) return;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [fullscreen]);

  const zoom = (next: number) => {
    const bounded = Math.max(1, Math.min(5, Number(next.toFixed(2))));
    scaleRef.current = bounded;
    setScale(bounded);
    if (bounded === 1) {
      offsetRef.current = { x: 0, y: 0 };
      setOffset(offsetRef.current);
    }
  };
  const move = (next: { x: number; y: number }) => {
    offsetRef.current = next;
    setOffset(next);
  };
  const reset = () => {
    scaleRef.current = 1;
    offsetRef.current = { x: 0, y: 0 };
    setScale(1);
    setOffset(offsetRef.current);
  };

  const startPinch = () => {
    const points = [...pointers.current.values()];
    if (points.length < 2) {
      pinching.current = null;
      return;
    }
    pinching.current = {
      distance: Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y),
      scale: scaleRef.current,
    };
    dragging.current = null;
  };

  if (failed) return <div className={styles.state}>Микрофотография недоступна</div>;
  if (!objectUrl) return <div className={styles.state}>Загружаем микрофотографию…</div>;

  return (
    <div className={[styles.shell, fullscreen ? styles.fullscreen : ""].filter(Boolean).join(" ")}>
      <div
        className={styles.viewport}
        onWheel={(event) => {
          event.preventDefault();
          zoom(scale + (event.deltaY < 0 ? .25 : -.25));
        }}
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
          if (pointers.current.size >= 2) {
            startPinch();
          } else if (scaleRef.current > 1) {
            dragging.current = {
              x: event.clientX,
              y: event.clientY,
              ox: offsetRef.current.x,
              oy: offsetRef.current.y,
            };
          }
        }}
        onPointerMove={(event) => {
          if (!pointers.current.has(event.pointerId)) return;
          pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
          if (pointers.current.size >= 2 && pinching.current) {
            const points = [...pointers.current.values()];
            const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
            if (pinching.current.distance > 0) {
              zoom(pinching.current.scale * distance / pinching.current.distance);
            }
            return;
          }
          if (!dragging.current) return;
          move({
            x: dragging.current.ox + event.clientX - dragging.current.x,
            y: dragging.current.oy + event.clientY - dragging.current.y,
          });
        }}
        onPointerUp={(event) => {
          pointers.current.delete(event.pointerId);
          dragging.current = null;
          startPinch();
        }}
        onPointerCancel={(event) => {
          pointers.current.delete(event.pointerId);
          dragging.current = null;
          startPinch();
        }}
        onDoubleClick={() => scaleRef.current > 1 ? reset() : zoom(2)}
      >
        <div
          className={styles.canvas}
          style={{ transform: `translate3d(${offset.x}px, ${offset.y}px, 0) scale(${scale})` }}
        >
          <img src={objectUrl} alt={alt} draggable={false} />
          {showMarkers && markers.map((marker, index) => (
            <span
              key={`${marker.label}-${index}`}
              className={styles.marker}
              style={{ left: `${marker.x}%`, top: `${marker.y}%` }}
              aria-label={marker.label}
              title={marker.label}
            >{index + 1}</span>
          ))}
        </div>
      </div>

      <div className={styles.controls} aria-label="Управление масштабом">
        <button type="button" onClick={() => zoom(scale - .5)} disabled={scale <= 1} aria-label="Уменьшить">
          <Icon icon={Minus} size={18} />
        </button>
        <span>{Math.round(scale * 100)}%</span>
        <button type="button" onClick={() => zoom(scale + .5)} disabled={scale >= 5} aria-label="Увеличить">
          <Icon icon={Plus} size={18} />
        </button>
        <button type="button" onClick={reset} aria-label="Сбросить масштаб">
          <Icon icon={RotateCcw} size={17} />
        </button>
        <button
          type="button"
          onClick={() => setFullscreen((value) => !value)}
          aria-label={fullscreen ? "Выйти из полноэкранного режима" : "Открыть на весь экран"}
        >
          <Icon icon={fullscreen ? Minimize2 : Maximize2} size={17} />
        </button>
        {markers.length > 0 && (
          <button
            type="button"
            className={showMarkers ? styles.active : undefined}
            onClick={() => setShowMarkers((value) => !value)}
            aria-label="Показать или скрыть метки"
          >
            <Icon icon={LocateFixed} size={17} />
          </button>
        )}
      </div>
      <div className={styles.hint}>Разведите два пальца или используйте кнопки · увеличенное изображение можно двигать</div>
    </div>
  );
}
