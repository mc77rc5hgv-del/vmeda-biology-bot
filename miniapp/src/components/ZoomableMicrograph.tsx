import { LocateFixed, Minus, Plus, RotateCcw } from "lucide-react";
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
  const dragging = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

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

  const zoom = (next: number) => setScale(Math.max(1, Math.min(5, Number(next.toFixed(2)))));
  const reset = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };

  if (failed) return <div className={styles.state}>Микрофотография недоступна</div>;
  if (!objectUrl) return <div className={styles.state}>Загружаем микрофотографию…</div>;

  return (
    <div className={styles.shell}>
      <div
        className={styles.viewport}
        onWheel={(event) => {
          event.preventDefault();
          zoom(scale + (event.deltaY < 0 ? .25 : -.25));
        }}
        onPointerDown={(event) => {
          if (scale <= 1) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          dragging.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y };
        }}
        onPointerMove={(event) => {
          if (!dragging.current) return;
          setOffset({
            x: dragging.current.ox + event.clientX - dragging.current.x,
            y: dragging.current.oy + event.clientY - dragging.current.y,
          });
        }}
        onPointerUp={() => { dragging.current = null; }}
        onPointerCancel={() => { dragging.current = null; }}
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
      <div className={styles.hint}>Используйте кнопки масштабирования · при увеличении изображение можно двигать</div>
    </div>
  );
}
