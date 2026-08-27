# Автоматическое добавление предметов из Telegram

Конвейер синхронизирует файлы из конкретной темы Telegram-группы, извлекает текст, передаёт материалы Codex,
проверяет `course_spec.json` и публикует предмет в `generated_courses/`. Бот загружает все JSON из этой
папки при старте, поэтому для следующего предмета править `telegram_bot.py` не требуется.

## Однократная настройка

1. Создайте отдельный служебный Telegram-аккаунт и получите `api_id`/`api_hash` на `my.telegram.org`.
2. Установите зависимости: `pip install -r requirements-automation.txt`.
3. Скопируйте `course-automation.example.json` в `course-automation.json` и задайте `chat`, `topic_id`, `slug`,
   `title`.
4. Установите переменные `TELEGRAM_API_ID` и `TELEGRAM_API_HASH`. Не сохраняйте их в Git.
5. Убедитесь, что команда `codex` доступна в PATH и авторизована.

Сначала получите каталог тем группы. Команда помечает предметы, которые уже есть в боте, и сохраняет остальные
в `topic_catalog.json`:

```powershell
python -m scripts.course_automation.pipeline discover --config course-automation.json
```

При первом запуске Telethon запросит телефон, код Telegram и пароль 2FA. Сессия сохраняется в `.secrets/`,
которая исключена из Git. В последующих запусках вход не требуется.

## Полный запуск

```powershell
python -m scripts.course_automation.pipeline run-all --config course-automation.json
```

Отдельные стадии:

```powershell
python -m scripts.course_automation.pipeline sync --config course-automation.json
python -m scripts.course_automation.pipeline extract --config course-automation.json
python -m scripts.course_automation.pipeline process --config course-automation.json
python -m scripts.course_automation.pipeline validate --config course-automation.json
python -m scripts.course_automation.pipeline publish --config course-automation.json
```

Для полностью автоматического режима запускайте `run-all` по расписанию. Публикация меняет только
`generated_courses/<slug>.json`; затем обычный CI выполняет тесты, а Railway получает обновление после слияния в
`main`.

## MCP

`aiogram 3.7` и актуальный MCP SDK требуют несовместимые версии `pydantic`, поэтому MCP запускается в
отдельном окружении. Сам конвейер и бот от MCP не зависят.

```powershell
python -m venv .venv-mcp
.venv-mcp\Scripts\pip install -r requirements-automation.txt -r requirements-mcp.txt
```

Запуск stdio MCP-сервера:

```powershell
.venv-mcp\Scripts\python -m scripts.course_automation.mcp_server
```

Он предоставляет инструменты `discover_telegram_subjects`, `sync_telegram_topic`, `extract_course_sources`,
`build_course_with_codex`, `validate_course` и `publish_course`. Все инструменты принимают путь к локальному
конфигурационному JSON.

## Безопасность

- Не передавайте `api_hash`, коды входа и `.session` в сообщения или репозиторий.
- Используйте отдельный Telegram-аккаунт только с доступом к необходимым учебным группам.
- Не обходите Telegram Content Protection.
- Изменения медицинского контента перед публикацией в `main` должны проходить просмотр diff/PR.
