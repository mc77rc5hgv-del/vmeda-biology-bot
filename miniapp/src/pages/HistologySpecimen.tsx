import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, BookOpen, Images, Lock, Microscope, ScanSearch } from "lucide-react";
import { useRef, useState, type Ref } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { ZoomableMicrograph, type MicrographHandle } from "../components/ZoomableMicrograph";
import { ApiError, fetchHistologyCatalog, fetchHistologySpecimen, type HistologyCatalogScope } from "../lib/apiClient";
import { filterHistologyGroups, type HistologyCatalogLocation } from "../lib/histologyCatalog";
import { useTelegramBackButton } from "../lib/telegram";
import type { HistologySpecimen } from "../lib/types";
import styles from "./HistologySpecimen.module.css";

function SpecimenImages({ specimen, viewer }: { specimen: HistologySpecimen; viewer: Ref<MicrographHandle> }) {
  const [imageIndex, setImageIndex] = useState(0);
  const guide = specimen.imageGuides[imageIndex];
  const src = specimen.images[imageIndex];

  return (
    <div className={styles.gallery}>
      {specimen.images.length > 1 && (
        <div className={styles.imagePicker} role="group" aria-label="Выбор изображения">
          <p><Icon icon={Images} size={18} /> Изображение {imageIndex + 1} из {specimen.images.length}</p>
          <div>
            {specimen.images.map((image, index) => (
              <button type="button" key={image} aria-pressed={index === imageIndex}
                aria-label={`${specimen.imageGuides[index]?.kind === "diagram" ? "Схема" : "Изображение"} ${index + 1}`}
                onClick={() => setImageIndex(index)}>
                {index + 1}
              </button>
            ))}
          </div>
        </div>
      )}

      {src ? (
        <ZoomableMicrograph
          key={src}
          ref={viewer}
          src={src}
          alt={`${specimen.title} · ${guide?.kind === "diagram" ? "схема" : "микрофотография"} ${imageIndex + 1}`}
          markers={specimen.markers}
        />
      ) : <StateMessage icon={Images} title="Изображений пока нет" />}

      {guide && (
        <section className={styles.imageGuide} aria-live="polite">
          <h2><Icon icon={ScanSearch} size={20} /> {guide.kind === "diagram" ? "Что показано на схеме" : "Что видно на снимке"}</h2>
          <p>{guide.visible}</p>
          {guide.kind === "diagram" && <p className={styles.guideNote}>Учебная схема · не в масштабе</p>}
          {guide.note && <p className={styles.guideNote}>{guide.note}</p>}
        </section>
      )}

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

export function HistologySpecimenPage() {
  const { specimenId = "" } = useParams();
  const navigate = useNavigate();
  const viewer = useRef<MicrographHandle>(null);
  const location = useLocation();
  const state = location.state as HistologyCatalogLocation | null;
  const param = new URLSearchParams(location.search).get("scope");
  const requestedScope = param === "diagnostics" || state?.catalogPath === "/histology/diagnostics" ? "diagnostics" : "exam";
  const legacyLink = !param && !state;
  const query = useQuery({
    queryKey: ["histology-specimen", specimenId, requestedScope, legacyLink],
    queryFn: async () => {
      let scope: HistologyCatalogScope = requestedScope;
      try {
        return { scope, specimen: await fetchHistologySpecimen(specimenId, scope) };
      } catch (error) {
        if (!legacyLink || !(error instanceof ApiError) || error.status !== 404) throw error;
        scope = "diagnostics";
        return { scope, specimen: await fetchHistologySpecimen(specimenId, scope) };
      }
    },
  });
  const scope = query.data?.scope ?? requestedScope;
  const catalogPath = scope === "diagnostics" ? "/histology/diagnostics" : "/histology/exam/specimens";
  const catalogSearch = state?.catalogSearch ?? "";
  function backToCatalog() {
    if (viewer.current?.closeFullscreen()) return;
    if (typeof state?.catalogSearch === "string") navigate(-1);
    else navigate(catalogPath);
  }
  useTelegramBackButton(backToCatalog);

  const catalogQuery = useQuery({ queryKey: ["histology-catalog", scope], queryFn: () => fetchHistologyCatalog(scope) });

  const specimen = query.data?.specimen;
  const specimens = filterHistologyGroups(catalogQuery.data?.groups ?? [], new URLSearchParams(catalogSearch))
    .flatMap((group) => group.specimens);
  const position = specimens.findIndex((item) => item.id === specimenId);
  const previous = position > 0 ? specimens[position - 1] : undefined;
  const next = position >= 0 ? specimens[position + 1] : undefined;
  function openSpecimen(id: string) {
    navigate(`/histology/specimens/${encodeURIComponent(id)}?scope=${scope}`, { state, replace: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  const backButton = (
    <button type="button" className={styles.backButton} onClick={backToCatalog}>
      <Icon icon={ArrowLeft} size={18} /> {catalogPath === "/histology/diagnostics" ? "Диагностики" : "Препараты"}
    </button>
  );
  if (query.isError || !specimen) {
    return (
      <div className={`screen ${styles.screen}`}>
        {backButton}
        {query.isLoading ? (
          <><Skeleton height={36} width="55%" /><Skeleton height={360} radius="22px" /></>
        ) : query.error instanceof ApiError && query.error.status === 403 ? (
          <StateMessage icon={Lock} title="Препарат закрыт" body={query.error.message} onRetry={() => navigate("/profile/subscriptions")} actionLabel="Открыть подписки" />
        ) : <StateMessage title="Не удалось открыть препарат" onRetry={() => query.refetch()} />}
      </div>
    );
  }
  const paragraphs = specimen.protocol.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean);

  return (
    <div className={`screen ${styles.screen}`}>
      {backButton}
      <header className={styles.header}>
        <div className={styles.kicker}><Icon icon={Microscope} size={17} /> Препарат №{specimen.number} <span>· {specimen.groupTitle.split(": ")[0]}</span></div>
        <h1>{specimen.title}</h1>
        {(specimen.stain || specimen.magnification) && (
          <div className={styles.meta}>
            {specimen.stain && <span>{specimen.stain}</span>}
            {specimen.magnification && <span>Исходный препарат ×{specimen.magnification}</span>}
          </div>
        )}
      </header>

      <div className={styles.studyLayout}>
        <SpecimenImages key={specimen.id} specimen={specimen} viewer={viewer} />
        <section className={styles.theory}>
          <h2><Icon icon={BookOpen} size={20} /> Как распознать препарат</h2>
          <div className={styles.protocol}>
            {paragraphs.map((paragraph, index) => {
              const heading = /^(Ориентиры[^:\n]*|Отличие[^:\n]*):\s*/.exec(paragraph);
              return (
                <div key={index}>
                  {heading && <h3>{heading[1]}</h3>}
                  <p>{heading ? paragraph.slice(heading[0].length) : paragraph}</p>
                </div>
              );
            })}
          </div>
          {specimen.metadataNote && <p className={styles.metadataNote}>{specimen.metadataNote}</p>}
        </section>
      </div>

      {catalogQuery.isError ? (
        <StateMessage title="Не удалось загрузить переходы между препаратами" onRetry={() => catalogQuery.refetch()} />
      ) : catalogQuery.isLoading ? <Skeleton height={52} /> : position >= 0 && (
        <nav className={styles.specimenNavigation} aria-label="Переходы между препаратами">
          <p>Препарат {position + 1} из {specimens.length}</p>
          <div>
            <button type="button" disabled={!previous} onClick={() => previous && openSpecimen(previous.id)}>
              <Icon icon={ArrowLeft} size={18} /> Предыдущий
            </button>
            <button type="button" className={styles.nextButton} onClick={() => next ? openSpecimen(next.id) : backToCatalog()}>
              {next ? "Следующий" : "К списку"}<Icon icon={ArrowRight} size={18} />
            </button>
          </div>
        </nav>
      )}
    </div>
  );
}
