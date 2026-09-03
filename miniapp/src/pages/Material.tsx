import { useQuery } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import { useNavigate, useParams } from "react-router-dom";
import { fetchMaterial } from "../lib/api";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import { AuthenticatedImage } from "../components/AuthenticatedImage";
import styles from "./Material.module.css";

export function MaterialPage() {
  const { subjectId = "", sectionId = "", materialId = "1" } = useParams();
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate(`/subjects/${subjectId}`));

  const materialQuery = useQuery({
    queryKey: ["material", subjectId, sectionId, materialId],
    queryFn: () => fetchMaterial(subjectId, sectionId, materialId),
  });

  if (materialQuery.isLoading) {
    return (
      <div className="screen">
        <Skeleton height={24} width="70%" />
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} height={90} radius="16px" />
        ))}
      </div>
    );
  }

  if (materialQuery.isError || !materialQuery.data) {
    return (
      <div className="screen">
        <StateMessage title="Материал не найден" onRetry={() => materialQuery.refetch()} />
      </div>
    );
  }

  const material = materialQuery.data;
  const safeHtml = DOMPurify.sanitize(material.rawHtml ?? "", {
    ALLOWED_TAGS: ["a", "b", "blockquote", "br", "code", "del", "em", "i", "p", "pre", "s", "strong", "u"],
    ALLOWED_ATTR: ["href", "title"],
  });
  const order = material.order;
  const total = material.totalInSection;
  // Реальный контент (см. lib/apiClient.ts) присылает готовые id соседей — id вида "core_p1_1"
  // не образуют предсказуемую числовую последовательность, в отличие от mock-материалов
  // (lib/mockData.ts), где id == order и "следующий" можно просто прибавлением единицы.
  const isRealContent = material.prevId !== undefined;

  function goTo(nextMaterialId: string) {
    hapticImpact("light");
    navigate(`/materials/${subjectId}/${sectionId}/${nextMaterialId}`);
  }

  function goBackToList() {
    if (material.groupId) {
      navigate(`/subjects/${subjectId}/sections/${sectionId}/groups/${material.groupId}`);
    } else {
      navigate(`/subjects/${subjectId}/sections/${sectionId}`);
    }
  }

  const hasPrev = isRealContent ? material.prevId != null : order > 1;
  const hasNext = isRealContent ? material.nextId != null : order < total;

  function handlePrev() {
    if (isRealContent && material.prevId) goTo(material.prevId);
    else if (!isRealContent) goTo(String(order - 1));
  }

  function handleNext() {
    if (isRealContent) {
      if (material.nextId) goTo(material.nextId);
      else goBackToList();
    } else if (order < total) {
      goTo(String(order + 1));
    } else {
      navigate(`/subjects/${subjectId}`);
    }
  }

  return (
    <div className="screen">
      <div className={styles.header}>
        <span className={styles.eyebrow}>
          Тема {order} из {total}
        </span>
        <h1 className={styles.title}>{material.title}</h1>
      </div>

      {isRealContent ? (
        <Card className={styles.block}>
          {/* Импортируемые материалы проходят DOMPurify: Telegram-источник нельзя считать
              вечным доверенным источником только потому, что результат сохранён в JSON. */}
          <div className={styles.blockBody} dangerouslySetInnerHTML={{ __html: safeHtml }} />
        </Card>
      ) : (
        material.blocks.map((block) => (
          <Card key={block.kind} className={styles.block}>
            <span className={styles.blockTitle}>{block.title}</span>
            <p className={styles.blockBody}>{block.body}</p>
          </Card>
        ))
      )}

      {material.media && material.media.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {material.media.map((m, i) => (
            <figure key={i} style={{ margin: 0 }}>
              <AuthenticatedImage src={m.url} alt={m.caption || `Иллюстрация ${i + 1}`} className={styles.media} />
              {m.caption && (
                <figcaption style={{ fontSize: 12, color: "var(--ink-secondary)", marginTop: 4 }}>
                  {m.caption}
                </figcaption>
              )}
            </figure>
          ))}
        </div>
      )}

      {material.sources && material.sources.length > 0 && (
        <p style={{ fontSize: 12, color: "var(--ink-secondary)" }}>
          📎 Источники: {material.sources.join(", ")}
        </p>
      )}

      <div className={styles.nav}>
        <button
          type="button"
          className={`${styles.navButton} ${styles.navSecondary}`}
          disabled={!hasPrev}
          onClick={handlePrev}
        >
          Назад
        </button>
        <button type="button" className={`${styles.navButton} ${styles.navPrimary}`} onClick={handleNext}>
          {hasNext ? "Понятно, дальше" : "Завершить раздел"}
        </button>
      </div>
    </div>
  );
}
