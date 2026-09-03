// Хранилище session-токена, выданного web_api после проверки initData (см. web_api/session.py).
// sessionStorage, не localStorage — токен живёт ровно с сессией вкладки/окна Mini App, что
// разумно соответствует его собственному TTL на сервере (несколько часов, не "навсегда") и не
// переживает закрытие приложения, как и должен короткоживущий токен.
const STORAGE_KEY = "vmeda_session_token";

export function getStoredSessionToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    // sessionStorage недоступен (приватный режим/некоторые встроенные браузеры) — работаем так,
    // будто токена никогда не было, а не падаем.
    return null;
  }
}

export function storeSessionToken(token: string): void {
  try {
    sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // см. getStoredSessionToken — тихо игнорируем, токен просто не переживёт эту сессию вкладки
  }
}

export function clearStoredSessionToken(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // см. выше
  }
}
