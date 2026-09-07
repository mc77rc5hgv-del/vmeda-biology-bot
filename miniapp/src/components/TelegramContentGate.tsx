import { BookOpen } from "lucide-react";
import { StateMessage } from "./StateMessage";

const BOT_URL = "https://t.me/vmeda_examen_bot";

/**
 * Публичная Railway-ссылка нужна для просмотра интерфейса, но учебный контент нельзя открывать
 * без проверенной Telegram-сессии. Вместо ложного 404 показываем причину и безопасный путь дальше.
 */
export function TelegramContentGate() {
  return (
    <StateMessage
      icon={BookOpen}
      title="Открой материалы через Telegram"
      body="В браузере доступен просмотр структуры предмета. Полные материалы открываются из бота после безопасной проверки Telegram-сессии."
      actionLabel="Открыть @vmeda_examen_bot"
      onRetry={() => window.location.assign(BOT_URL)}
    />
  );
}
