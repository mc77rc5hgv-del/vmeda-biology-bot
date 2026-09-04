import { Compass } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTelegramBackButton } from "../lib/telegram";
import { StateMessage } from "../components/StateMessage";

export function NotFoundPage() {
  const navigate = useNavigate();
  useTelegramBackButton(() => navigate("/"));

  return (
    <div className="screen">
      <StateMessage
        icon={Compass}
        title="Страница не найдена"
        body="Такого экрана нет — вернись на главную."
        onRetry={() => navigate("/")}
        actionLabel="На главную"
      />
    </div>
  );
}
