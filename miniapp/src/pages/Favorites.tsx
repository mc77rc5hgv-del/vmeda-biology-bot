import { Bookmark, Trash2 } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchLearningState, setLearningFlag } from "../lib/api";
import type { LearningMaterialState } from "../lib/types";
import { hapticImpact, useTelegramBackButton } from "../lib/telegram";
import { Card } from "../components/Card";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { StateMessage } from "../components/StateMessage";
import styles from "./ProfileDetails.module.css";

export function FavoritesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useTelegramBackButton(() => navigate("/profile"));
  const learningQuery = useQuery({ queryKey: ["learning"], queryFn: fetchLearningState });
  const removeMutation = useMutation({
    mutationFn: (item: LearningMaterialState) => setLearningFlag({ subjectId: item.subjectId, sectionId: item.sectionId, materialId: item.materialId }, "favorite", false),
    onSuccess: (nextState) => queryClient.setQueryData(["learning"], nextState),
  });

  if (learningQuery.isLoading) return <div className="screen"><Skeleton height={62} width="55%" />{Array.from({ length: 3 }).map((_, index) => <Skeleton key={index} height={76} radius="16px" />)}</div>;
  if (learningQuery.isError || !learningQuery.data) return <div className="screen"><StateMessage title="Не удалось загрузить избранное" onRetry={() => learningQuery.refetch()} /></div>;

  const favorites = learningQuery.data.favorites;
  return (
    <div className="screen">
      <header className={styles.intro}><h1 className={styles.title}>Избранное</h1><p className={styles.subtitle}>Сохранённые темы доступны здесь и на странице прогресса.</p></header>
      {removeMutation.isError && <StateMessage title="Не удалось изменить избранное" body="Проверь соединение и повтори действие. Сохранённая тема остаётся в списке." />}
      {favorites.length === 0 ? (
        <StateMessage icon={Bookmark} title="В избранном пока пусто" body="Открой учебный материал и нажми на закладку — тема появится здесь." onRetry={() => navigate("/")} actionLabel="Перейти к предметам" />
      ) : (
        <div className={styles.list}>
          {favorites.map((item) => {
            const key = [item.subjectId, item.sectionId, item.materialId].join("/");
            return (
              <Card key={key} className={styles.favoriteCard}>
                <button type="button" className={styles.favoriteMain} onClick={() => navigate("/materials/" + item.subjectId + "/" + item.sectionId + "/" + item.materialId)}>
                  <div className={styles.favoriteName}>{item.materialTitle || "Учебный материал"}</div>
                  <div className={styles.favoriteMeta}>{item.subjectTitle || item.subjectId} · {item.sectionTitle || item.sectionId}</div>
                </button>
                <button type="button" className={styles.removeButton} aria-label={"Удалить из избранного: " + item.materialTitle} disabled={removeMutation.isPending} onClick={() => { hapticImpact("light"); removeMutation.mutate(item); }}>
                  <Icon icon={Trash2} size={19} />
                </button>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
