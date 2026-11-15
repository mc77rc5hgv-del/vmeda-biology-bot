import { LocateFixed, Maximize2, Minimize2, Minus, Plus, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type PointerEvent, type Ref } from "react";
import { fetchAuthorizedBlob } from "../lib/apiClient";
import type { HistologyMarker } from "../lib/types";
import { Icon } from "./Icon";
import styles from "./ZoomableMicrograph.module.css";

interface Props {
  src: string;
  alt: string;
  markers?: HistologyMarker[];
  ref?: Ref<MicrographHandle>;
}

export interface MicrographHandle {
  closeFullscreen(): boolean;
}

type Point = { x: number; y: number };
type View = { scale: number; offset: Point };

const initialView: View = { scale: 1, offset: { x: 0, y: 0 } };
const clampScale = (scale: number) => Math.max(1, Math.min(5, Number(scale.toFixed(2))));

function pinchGeometry(points: Point[], bounds: DOMRect) {
  const [a, b] = points;
  return {
    distance: Math.hypot(a.x - b.x, a.y - b.y),
    anchor: { x: (a.x + b.x) / 2 - bounds.left - bounds.width / 2, y: (a.y + b.y) / 2 - bounds.top - bounds.height / 2 },
  };
}

export function ZoomableMicrograph({ src, alt, markers = [], ref }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState(initialView);
  const [ready, setReady] = useState(false);
  const [showMarkers, setShowMarkers] = useState(true);
  const [fullscreen, setFullscreen] = useState(false);
  const [inlineHeight, setInlineHeight] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const imageSize = useRef({ width: 0, height: 0 });
  const fullscreenButton = useRef<HTMLButtonElement>(null);
  const restoreFocus = useRef(false);
  const currentView = useRef(initialView);
  const pointers = useRef(new Map<number, Point>());
  const dragging = useRef<{ start: Point; offset: Point } | null>(null);
  const pinching = useRef<{ distance: number; anchor: Point; view: View } | null>(null);

  const updateView = useCallback((scale: number, offset: Point) => {
    const viewportNode = viewport.current;
    const width = viewportNode?.clientWidth ?? 0;
    const height = viewportNode?.clientHeight ?? 0;
    const { width: naturalWidth, height: naturalHeight } = imageSize.current;
    const fit = width && height && naturalWidth && naturalHeight
      ? Math.min(width / naturalWidth, height / naturalHeight)
      : undefined;
    const maxX = fit === undefined ? Math.abs(offset.x) : Math.max(0, (naturalWidth * fit * scale - width) / 2);
    const maxY = fit === undefined ? Math.abs(offset.y) : Math.max(0, (naturalHeight * fit * scale - height) / 2);
    const x = Math.max(-maxX, Math.min(maxX, offset.x));
    const y = Math.max(-maxY, Math.min(maxY, offset.y));
    const previous = currentView.current;
    if (previous.scale === scale && previous.offset.x === x && previous.offset.y === y) return;
    const next = { scale, offset: { x, y } };
    currentView.current = next;
    setView(next);
  }, []);

  function clearGesture() {
    pointers.current.clear();
    dragging.current = null;
    pinching.current = null;
  }

  function closeFullscreen() {
    if (!fullscreen) return false;
    clearGesture();
    setFullscreen(false);
    return true;
  }

  useImperativeHandle(ref, () => ({ closeFullscreen }));

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

  useLayoutEffect(() => {
    const node = viewport.current;
    if (!node) return;
    const fitView = () => {
      const { scale, offset } = currentView.current;
      updateView(scale, offset);
    };
    fitView();
    const observer = new ResizeObserver(fitView);
    observer.observe(node);
    return () => observer.disconnect();
  }, [fullscreen, updateView]);

  function zoom(next: number) {
    const previous = currentView.current;
    const scale = clampScale(next);
    const ratio = scale / previous.scale;
    updateView(scale, { x: previous.offset.x * ratio, y: previous.offset.y * ratio });
  }

  function endPointer(event: PointerEvent<HTMLDivElement>) {
    if (!pointers.current.delete(event.pointerId)) return;
    pinching.current = null;
    const remaining = pointers.current.values().next().value;
    dragging.current = remaining ? { start: remaining, offset: currentView.current.offset } : null;
  }

  function movePointer(event: PointerEvent<HTMLDivElement>) {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    const pinch = pinching.current;
    if (pinch && pinch.distance > 0) {
      const { distance, anchor } = pinchGeometry([...pointers.current.values()], event.currentTarget.getBoundingClientRect());
      const scale = clampScale(pinch.view.scale * distance / pinch.distance);
      const ratio = scale / pinch.view.scale;
      updateView(scale, {
        x: anchor.x + (pinch.view.offset.x - pinch.anchor.x) * ratio,
        y: anchor.y + (pinch.view.offset.y - pinch.anchor.y) * ratio,
      });
      return;
    }
    const drag = dragging.current;
    if (drag && currentView.current.scale > 1) {
      updateView(currentView.current.scale, {
        x: drag.offset.x + event.clientX - drag.start.x,
        y: drag.offset.y + event.clientY - drag.start.y,
      });
    }
  }

  const { scale, offset } = view;
  const reset = () => updateView(initialView.scale, initialView.offset);
  const toggleFullscreen = () => {
    if (!closeFullscreen()) {
      setInlineHeight(shell.current?.getBoundingClientRect().height ?? 0);
      clearGesture();
      setFullscreen(true);
    }
  };

  const content = (
    <>
      <div
        className={styles.viewport}
        ref={viewport}
        data-zoomed={scale > 1}
        tabIndex={ready ? 0 : undefined}
        role="group"
        aria-label="Область просмотра микрофотографии"
        onKeyDown={(event) => {
          if (event.key === "+" || event.key === "=") zoom(scale + .5);
          else if (event.key === "-") zoom(scale - .5);
          else if (event.key === "0") reset();
          else {
            const x = event.key === "ArrowLeft" ? 48 : event.key === "ArrowRight" ? -48 : 0;
            const y = event.key === "ArrowUp" ? 48 : event.key === "ArrowDown" ? -48 : 0;
            if (scale <= 1 || (!x && !y)) return;
            updateView(scale, { x: offset.x + x, y: offset.y + y });
          }
          event.preventDefault();
        }}
        onWheel={(event) => {
          if (fullscreen && event.deltaY !== 0) zoom(currentView.current.scale + (event.deltaY < 0 ? .25 : -.25));
        }}
        onPointerDown={(event) => {
          if (!ready || event.button !== 0 || pointers.current.size >= 2) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          const point = { x: event.clientX, y: event.clientY };
          pointers.current.set(event.pointerId, point);
          const viewAtStart = currentView.current;
          if (pointers.current.size === 2) {
            pinching.current = { ...pinchGeometry([...pointers.current.values()], event.currentTarget.getBoundingClientRect()), view: viewAtStart };
            dragging.current = null;
          } else {
            dragging.current = { start: point, offset: viewAtStart.offset };
          }
        }}
        onPointerMove={movePointer}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        onLostPointerCapture={endPointer}
        onDoubleClick={() => {
          if (!ready) return;
          if (currentView.current.scale > 1) reset();
          else zoom(2);
        }}
      >
        {objectUrl && !failed ? <div
          className={styles.canvas}
          style={{ transform: `translate3d(${offset.x}px, ${offset.y}px, 0) scale(${scale})` }}
        >
          <img src={objectUrl} alt={alt} draggable={false}
            onLoad={(event) => {
              imageSize.current = { width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight };
              setReady(true);
              updateView(currentView.current.scale, currentView.current.offset);
            }}
            onError={() => { setReady(false); setFailed(true); }} />
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

      <div className={styles.controls} role="group" aria-label="Управление масштабом">
        <button type="button" onClick={() => zoom(scale - .5)} disabled={scale <= 1 || !ready} aria-label="Уменьшить" title="Уменьшить">
          <Icon icon={Minus} size={18} />
        </button>
        <span>{Math.round(scale * 100)}%</span>
        <button type="button" onClick={() => zoom(scale + .5)} disabled={scale >= 5 || !ready} aria-label="Увеличить" title="Увеличить">
          <Icon icon={Plus} size={18} />
        </button>
        <button type="button" onClick={reset} disabled={scale <= 1 || !ready} aria-label="Сбросить масштаб" title="Сбросить масштаб">
          <Icon icon={RotateCcw} size={17} />
        </button>
        <button
          type="button"
          ref={fullscreenButton}
          className={fullscreen ? styles.closeButton : undefined}
          disabled={!fullscreen && !ready}
          onClick={toggleFullscreen}
          aria-label={fullscreen ? "Выйти из полноэкранного режима" : "Открыть на весь экран"}
          title={fullscreen ? "Выйти из полноэкранного режима" : "Открыть на весь экран"}
        >
          <Icon icon={fullscreen ? Minimize2 : Maximize2} size={17} />
          {fullscreen && "Закрыть"}
        </button>
        {markers.length > 0 && (
          <button
            type="button"
            className={showMarkers ? styles.active : undefined}
            onClick={() => setShowMarkers((value) => !value)}
            aria-pressed={showMarkers}
            disabled={!ready}
            aria-label="Показать или скрыть метки"
          >
            <Icon icon={LocateFixed} size={17} />
          </button>
        )}
      </div>
      <div className={styles.hint}>{fullscreen ? "Разведи два пальца или используй кнопки масштаба" : "Увеличенное изображение можно перетаскивать"}</div>
    </>
  );

  return fullscreen ? (
    <>
      <div style={{ height: inlineHeight }} aria-hidden="true" />
      <dialog ref={dialog} className={`${styles.shell} ${styles.fullscreen}`} aria-label="Просмотр изображения"
        onCancel={(event) => {
          event.preventDefault();
          closeFullscreen();
        }}>
        {content}
      </dialog>
    </>
  ) : (
    <div className={styles.shell} ref={shell}>{content}</div>
  );
}
