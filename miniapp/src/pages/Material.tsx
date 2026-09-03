import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { fetchMaterial } from "../lib/api";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
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
  const order = material.order;
  const total = material.totalInSection;

  function goToOrder(nextOrder: number) {
    hapticImpact("light");
    navigate(`/materials/${subjectId}/${sectionId}/${nextOrder}`);
  }

  return (
    <div className="screen">
      <div className={styles.header}>
        <span className={styles.eyebrow}>
          Тема {order} из {total}
        </span>
        <h1 className={styles.title}>{material.title}</h1>
      </div>

      {material.blocks.map((block) => (
        <Card key={block.kind} className={styles.block}>
          <span className={styles.blockTitle}>{block.title}</span>
          <p className={styles.blockBody}>{block.body}</p>
        </Card>
      ))}

      <div className={styles.nav}>
        <button
          type="button"
          className={`${styles.navButton} ${styles.navSecondary}`}
          disabled={order <= 1}
          onClick={() => goToOrder(order - 1)}
        >
          Назад
        </button>
        <button
          type="button"
          className={`${styles.navButton} ${styles.navPrimary}`}
          onClick={() => (order < total ? goToOrder(order + 1) : navigate(`/subjects/${subjectId}`))}
        >
          {order < total ? "Понятно, дальше" : "Завершить раздел"}
        </button>
      </div>
    </div>
  );
}
