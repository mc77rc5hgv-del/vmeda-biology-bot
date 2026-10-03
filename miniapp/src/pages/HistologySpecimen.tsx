import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Images, Microscope } from "lucide-react";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { ZoomableMicrograph } from "../components/ZoomableMicrograph";
import { fetchHistologySpecimen } from "../lib/apiClient";
import { useTelegramBackButton } from "../lib/telegram";
import styles from "./HistologySpecimen.module.css";

export function HistologySpecimenPage() {
  const { specimenId = "" } = useParams();
  const navigate = useNavigate();
  const [imageIndex, setImageIndex] = useState(0);
  useTelegramBackButton(() => navigate("/histology/exam"));

  const query = useQuery({
    queryKey: ["histology-specimen", specimenId],
    queryFn: () => fetchHistologySpecimen(specimenId),
  });

  if (query.isLoading) return <div className="screen"><Skeleton height={34} width="55%" /><Skeleton height={360} radius="22px" /></div>;
  if (query.isError || !query.data) {
    return <div className="screen"><StateMessage title="Препарат не найден" onRetry={() => query.refetch()} /></div>;
  }
  const specimen = query.data;
  const paragraphs = specimen.protocol.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean);

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
          {specimen.magnification && <span>Увеличение ×{specimen.magnification}</span>}
          <span>{specimen.groupTitle}</span>
        </div>
      </header>

      <ZoomableMicrograph
        key={specimen.images[imageIndex]}
        src={specimen.images[imageIndex]}
        alt={`${specimen.title}, изображение ${imageIndex + 1}`}
        markers={specimen.markers}
      />

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

      {specimen.markers.length > 0 && (
        <section className={styles.markerLegend}>
          <h2>Метки на изображении</h2>
          {specimen.markers.map((marker, index) => (
            <div key={`${marker.label}-${index}`}><span>{index + 1}</span>{marker.label}</div>
          ))}
        </section>
      )}
    </div>
  );
}
