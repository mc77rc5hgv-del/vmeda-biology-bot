# anatom-bot

`@Vmeda_anatom_bot` — лаунчер и канал уведомлений для MiniApp **АНАТОМ** (anatomapp.ru).

Обучение целиком живёт в MiniApp. Бот сознательно ничего из него не повторяет: он делает то,
чего приложение не может само — ставит кнопку запуска везде, дотягивается до студентов, которые
сейчас в приложение не смотрят, и даёт админам панель.

## Что делает бот

**Запуск MiniApp — в четырёх местах** (Telegram открывает MiniApp тремя типами кнопок, задействованы все):
- ☰ рядом с полем ввода (`MenuButtonWebApp`) — самый заметный вход;
- постоянная кнопка «🚀 Открыть АНАТОМ» над полем ввода (`KeyboardButton(web_app=…)`);
- большая кнопка в сообщениях (`InlineKeyboardButton(web_app=…)`) — на приветствии, в справке,
  в напоминаниях и **во всех рассылках**;
- команда `/app`.

**Уведомления** (`scheduler.py`) — ежедневное напоминание в местном часовом поясе, спасение серии
вечером, латинский термин дня утром, возврат неактивных, недельный дайджест. Каждое несёт кнопку запуска.

**Админ-панель** (`/admin` или кнопка «⚙️ Админ», видна только админам): статистика, топ-10,
последние регистрации, поиск по `@username`/ID, рассылка всем и отдельно «спящим» — с обязательным
предпросмотром и подтверждением перед отправкой.

## Аутентификация

Два пути, оба ведут к одному токену сессии:
- **Login Widget** (браузерная версия сайта) → `POST /auth/telegram`;
- **MiniApp** → `POST /auth/telegram-webapp` с `Telegram.WebApp.initData`. Внутри Telegram виджет
  входа не работает, и схема подписи там другая: секрет — `HMAC("WebAppData", bot_token)`, а не
  `sha256(bot_token)`. Перепутать их нельзя, это дыра — на что есть отдельный тест.

## API

`POST /auth/telegram` · `POST /auth/telegram-webapp` · `POST /auth/start` ·
`GET /auth/session/{code}` · `GET`/`PUT /api/state` (тело — `{"state": {...}}`) ·
`GET /api/leaderboard`.

Состояние — общий JSONB-блоб с приложением, формат задаёт фронтенд (см. docstring `DEFAULT_STATE`
в `db.py`). Ключ темы — `"<moduleId>:<topicNum>"`.

## Структура

- `config.py` — переменные окружения (`ANATOM_WEBAPP_URL` задаёт и URL MiniApp, и CORS-origin).
- `db.py` — модели, запросы рейтинга, идемпотентные миграции колонок.
- `auth.py` — проверка подписи Login Widget и initData, JWT-сессии.
- `api.py` — FastAPI.
- `bot.py`, `keyboards.py`, `texts.py`, `admin.py`, `scheduler.py`.
- `terms.json` — 1228 латинских терминов, нужны только для «термина дня».
- `modules.py`, `state_logic.py` — разбор общего состояния для напоминаний и админ-карточки.

## Разработка

```
pip install -r requirements.txt
cp .env.example .env       # ANATOM_BOT_TOKEN, DATABASE_URL, ANATOM_SESSION_SECRET
set -a && source .env && set +a

python3 bot.py                            # бот + планировщик
uvicorn api:app --reload --port 8000      # API

python3 -m unittest discover -s tests     # тесты (БД и токен не нужны)
```

## Деплой

Два сервиса Railway из одного репозитория, Root Directory `anatom_bot`, общий `DATABASE_URL`:
1. Бот: `python3 bot.py`
2. API: `uvicorn api:app --host 0.0.0.0 --port $PORT`

**MiniApp настраивается в BotFather** (Bot Settings → Menu Button / Mini App) на тот же адрес,
что и `ANATOM_WEBAPP_URL`. Бот выставляет кнопку меню при каждом старте, так что менять адрес
нужно в переменной окружения — ручная правка в BotFather будет перезаписана.

## Открытые вопросы

- Сайт ранжирует рейтинг из своей Supabase, а бот — из общей Postgres, поэтому таблицы расходятся.
  `GET /api/leaderboard` даёт единый источник; переключение — на стороне фронтенда.
- MiniApp должен вызывать `/auth/telegram-webapp` — иначе внутри Telegram вход не состоится.
