import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Images, Lock, Microscope } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { ZoomableMicrograph } from "../components/ZoomableMicrograph";
import { ApiError, fetchHistologyCatalog, fetchHistologySpecimen } from "../lib/apiClient";
import { useTelegramBackButton } from "../lib/telegram";
import styles from "./HistologySpecimen.module.css";

export function HistologySpecimenPage() {
  const { specimenId = "" } = useParams();
  const navigate = useNavigate();
  const [imageIndex, setImageIndex] = useState(0);
  const [imageSpecimenId, setImageSpecimenId] = useState(specimenId);
  if (imageSpecimenId !== specimenId) {
    setImageSpecimenId(specimenId);
    setImageIndex(0);
  }
  useTelegramBackButton(() => navigate("/histology/exam"));

  const query = useQuery({
    queryKey: ["histology-specimen", specimenId],
    queryFn: () => fetchHistologySpecimen(specimenId),
  });
  const catalogQuery = useQuery({ queryKey: ["histology-catalog"], queryFn: fetchHistologyCatalog });

  if (query.isLoading) return <div className="screen"><Skeleton height={34} width="55%" /><Skeleton height={360} radius="22px" /></div>;
  if (query.isError || !query.data) {
    if (query.error instanceof ApiError && query.error.status === 403) {
      return <div className="screen"><StateMessage icon={Lock} title="Препарат закрыт" body={query.error.message} onRetry={() => navigate("/profile/subscriptions")} actionLabel="Открыть подписки" /></div>;
    }
    return <div className="screen"><StateMessage title="Препарат не найден" onRetry={() => query.refetch()} /></div>;
  }
  const specimen = query.data;
  const specimens = catalogQuery.data?.groups.flatMap((group) => group.specimens) ?? [];
  const position = specimens.findIndex((item) => item.id === specimenId);
  const previous = position > 0 ? specimens[position - 1] : undefined;
  const next = position >= 0 ? specimens[position + 1] : undefined;
  function openSpecimen(id: string) {
    navigate(`/histology/specimens/${encodeURIComponent(id)}`);
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  const paragraphs = specimen.protocol.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean);
  const guide = specimen.imageGuides[imageIndex];

  return (
    <div className={["screen", styles.screen].join(" ")}>
      <button type="button" className={styles.backButton} onClick={() => navigate("/histology/exam")}>
        <Icon icon={ArrowLeft} size={18} /> ЭКЗАМЕН
      </button>

      <header className={styles.header}>
        <div className={styles.kicker}><Icon icon={Microscope} size={15} /> Препарат №{specimen.number}</div>
        <h1>{specimen.title}</h1>
        <div className={styles.meta}>
          {specimen.stain && <span>{specimen.stain}</span>}
          {specimen.magnification && <span>Исходный препарат ×{specimen.magnification}</span>}
          <span>{specimen.groupTitle}</span>
        </div>
        {specimen.metadataNote && <p className={styles.metadataNote}>{specimen.metadataNote}</p>}
      </header>

      <ZoomableMicrograph
        key={specimen.images[imageIndex]}
        src={specimen.images[imageIndex]}
        alt={`${specimen.title}, изображение ${imageIndex + 1}`}
        markers={specimen.markers}
      />

      {guide && (
        <section className={styles.imageGuide} aria-live="polite">
          <p className={styles.eyebrow}>{guide.kind === "diagram" ? "Учебная схема · не в масштабе" : `Кадр ${imageIndex + 1} · ориентиры`}</p>
          <p>{guide.visible}</p>
          {guide.note && <p className={styles.guideNote}>{guide.note}</p>}
        </section>
      )}

      {specimen.images.length > 1 && (
        <div className={styles.imagePicker}>
          <span><Icon icon={Images} size={15} /> Поля зрения</span>
          <div>
            {specimen.images.map((_, index) => (
              <button
                type="button"
                key={index}
                className={index === imageIndex ? styles.active : undefined}
                onClick={() => setImageIndex(index)}
              >{index + 1}</button>
            ))}
          </div>
        </div>
      )}

      <section className={styles.theory}>
        <p className={styles.eyebrow}>Теория и ориентиры</p>
        <h2>Как распознать препарат</h2>
        <div className={styles.protocol}>
          {paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}
        </div>
      </section>

      {specimen.sources.length > 0 && (
        <details className={styles.sources}>
          <summary>Учебные источники</summary>
          <ul>{specimen.sources.map((source) => (
            <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></li>
          ))}</ul>
        </details>
      )}

      {specimen.markers.length > 0 && (
        <section className={styles.markerLegend}>
          <h2>Метки на изображении</h2>
          {specimen.markers.map((marker, index) => (
            <div key={`${marker.label}-${index}`}><span>{index + 1}</span>{marker.label}</div>
          ))}
        </section>
      )}
      {catalogQuery.isError ? (
        <StateMessage title="Не удалось загрузить переходы между препаратами" onRetry={() => catalogQuery.refetch()} />
      ) : catalogQuery.isLoading ? <Skeleton height={52} /> : position >= 0 && (
        <nav className={styles.specimenNavigation} aria-label="Переходы между препаратами">
          <p>Препарат {position + 1} из {specimens.length}</p>
          <div>
            <button type="button" disabled={!previous} onClick={() => previous && openSpecimen(previous.id)}>
              <Icon icon={ArrowLeft} size={18} /> Предыдущий
            </button>
            <button type="button" className={styles.nextButton} onClick={() => next ? openSpecimen(next.id) : navigate("/histology/exam")}>
              {next ? "Следующий препарат" : "К списку препаратов"}<Icon icon={ArrowRight} size={18} />
            </button>
          </div>
        </nav>
      )}
    </div>
  );
}
