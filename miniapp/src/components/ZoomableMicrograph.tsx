import { LocateFixed, Maximize2, Minimize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
  const [attempt, setAttempt] = useState(0);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [showMarkers, setShowMarkers] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const fullscreenButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const dragging = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const pinching = useRef<{ distance: number; scale: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let url: string | null = null;
    fetchAuthorizedBlob(src, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setObjectUrl(url);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [attempt, src]);

  useLayoutEffect(() => {
    if (!fullscreen || !dialog.current) {
      if (restoreFocus.current) {
        fullscreenButton.current?.focus({ preventScroll: true });
        restoreFocus.current = false;
      }
      return;
    }
    const viewer = dialog.current;
    viewer.showModal();
    restoreFocus.current = true;
    fullscreenButton.current?.focus({ preventScroll: true });
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      viewer.close();
      document.body.style.overflow = previousOverflow;
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

  const content = (
    <>
      <div
        className={styles.viewport}
        data-zoomed={scale > 1}
        onWheel={(event) => {
          if (fullscreen && event.deltaY !== 0) zoom(scaleRef.current + (event.deltaY < 0 ? .25 : -.25));
        }}
        onPointerDown={(event) => {
          if (!objectUrl || failed) return;
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
        {objectUrl && !failed ? <div
          className={styles.canvas}
          style={{ transform: `translate3d(${offset.x}px, ${offset.y}px, 0) scale(${scale})` }}
        >
          <img src={objectUrl} alt={alt} draggable={false} onError={() => setFailed(true)} />
          {showMarkers && markers.map((marker, index) => (
            <span
              key={`${marker.label}-${index}`}
              className={styles.marker}
              style={{ left: `${marker.x}%`, top: `${marker.y}%` }}
              aria-label={marker.label}
              title={marker.label}
            >{index + 1}</span>
          ))}
        </div> : (
          <div className={styles.state}>
            {failed ? (
              <>
                <p role="status">Не удалось загрузить изображение</p>
                <button type="button" onClick={() => {
                  setObjectUrl(null);
                  setFailed(false);
                  setAttempt((previous) => previous + 1);
                }}>Повторить</button>
              </>
            ) : <p role="status">Загружаем изображение…</p>}
          </div>
        )}
      </div>

      <div className={styles.controls} aria-label="Управление масштабом">
        <button type="button" onClick={() => zoom(scale - .5)} disabled={scale <= 1 || !objectUrl || failed} aria-label="Уменьшить">
          <Icon icon={Minus} size={18} />
        </button>
        <span>{Math.round(scale * 100)}%</span>
        <button type="button" onClick={() => zoom(scale + .5)} disabled={scale >= 5 || !objectUrl || failed} aria-label="Увеличить">
          <Icon icon={Plus} size={18} />
        </button>
        <button type="button" onClick={reset} disabled={scale <= 1 || !objectUrl || failed} aria-label="Сбросить масштаб">
          <Icon icon={RotateCcw} size={17} />
        </button>
        <button
          type="button"
          ref={fullscreenButton}
          disabled={!fullscreen && (!objectUrl || failed)}
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
            aria-pressed={showMarkers}
            disabled={!objectUrl || failed}
            aria-label="Показать или скрыть метки"
          >
            <Icon icon={LocateFixed} size={17} />
          </button>
        )}
      </div>
      <div className={styles.hint}>Увеличенное изображение можно перетаскивать</div>
    </>
  );

  return fullscreen ? (
    <>
      <div className={styles.placeholder} />
      <dialog ref={dialog} className={`${styles.shell} ${styles.fullscreen}`} aria-label="Просмотр изображения"
        onCancel={(event) => {
          event.preventDefault();
          setFullscreen(false);
        }}>
        {content}
      </dialog>
    </>
  ) : (
    <div className={styles.shell}>{content}</div>
  );
}
