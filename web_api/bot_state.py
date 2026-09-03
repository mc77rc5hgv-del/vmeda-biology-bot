"""Мост к состоянию бота -- ЕДИНСТВЕННОЕ место в web_api, которое импортирует telegram_bot.

Почему это отдельный, узкий модуль, а не прямой `import telegram_bot` в каждом роутере (важная
находка Этапа 3, см. отчёт аудита): `services/access.py` сам делает `import telegram_bot as tb`
на верхнем уровне, чтобы читать `tb.stats`/`tb.SUBSCRIPTION_TIERS` -- то есть настоящее
направление зависимости сегодня "services.access -> telegram_bot", а не наоборот, как читается
из его собственного докстринга. Импортировать `services.access` НАПРЯМУЮ, в обход этого файла,
значит вслепую тянуть весь `telegram_bot.py`: конструктор `aiogram.Bot(token=BOT_TOKEN)` (падает
без валидного BOT_TOKEN — см. ниже), `Dispatcher()`, регистрацию ~50 хендлеров, загрузку всех
JSON-баз контента и конфигурацию AI-пайплайна. Это НЕ баг, который нужно чинить сейчас (задача
ТЗ §22 п.1 явно запрещает "переписывай весь бот") -- цена оправдана: web_api и так должен уметь
принимать решения о доступе ТОЧНО так же, как бот, а не заново их изобретать.

Что из этого следует практически:
1. web_api нужен тот же BOT_TOKEN, что и боту (тот же секрет, тот же процесс входа в Telegram
   Bot API) -- НЕ два разных бота, один и тот же.
2. Импорт НЕ делает сетевых вызовов сам по себе (Bot() только конструирует HTTP-клиент, polling
   стартует лишь внутри telegram_bot.main(), который web_api никогда не вызывает) -- но занимает
   заметное время (~3-4с на этом железе: загрузка ~20 JSON-файлов контента) -- один раз при
   старте процесса, не на каждый запрос.
3. `telegram_bot.stats` -- это ОБЫЧНЫЙ Python-словарь, загруженный В ПАМЯТЬ ОДИН РАЗ при импорте
   (см. CLAUDE.md "Stats persistence"). Если бот (отдельный процесс) с тех пор записал что-то
   новое в stats.json, копия web_api устареет молча -- никакого автоматического обновления нет.
   refresh_stats() ниже явно перечитывает файл с диска; вызывай её в начале каждого read-only
   запроса, которому нужны свежие данные (см. web_api/deps.py) -- недорого (простой JSON-парсинг),
   но НЕ бесплатно, поэтому не на каждую мелкую операцию внутри одного запроса, а один раз в его
   начале.
"""
import json
import os

_bot_module = None


class BotStateUnavailableError(RuntimeError):
    """Критическое состояние недоступно — API обязан закрыться, а не выдавать пустые права."""


def get_bot_module():
    """Ленивый импорт telegram_bot -- откладывает тяжёлую загрузку (и требование валидного
    BOT_TOKEN) до первого реального запроса/явного прогрева, а не до момента импорта самого
    web_api (важно для тестов auth.py/session.py выше, которым telegram_bot вообще не нужен)."""
    global _bot_module
    if _bot_module is None:
        if not os.environ.get("BOT_TOKEN"):
            raise BotStateUnavailableError(
                "BOT_TOKEN не задан -- web_api импортирует telegram_bot.py, а тот требует тот же "
                "токен, что и сам бот (см. docstring этого файла)."
            )
        if not os.environ.get("STATS_DIR"):
            raise BotStateUnavailableError(
                "STATS_DIR не задан явно: web_api не может доказать, что читает persistent volume бота"
            )
        import telegram_bot  # noqa: PLC0415 -- намеренно ленивый импорт, см. докстринг выше

        _bot_module = telegram_bot
    return _bot_module


def refresh_stats() -> None:
    """Перечитывает stats.json с диска и подменяет telegram_bot.stats -- см. пункт 3 в докстринге
    модуля. services.access читает tb.stats заново при каждом вызове (не кэширует ссылку сама),
    так что подмены самого объекта достаточно -- ничего больше переинициализировать не нужно."""
    tb = get_bot_module()
    if not os.path.isfile(tb.STATS_FILE):
        raise BotStateUnavailableError(
            f"файл состояния {tb.STATS_FILE!r} отсутствует; пустые права намеренно не создаются"
        )
    try:
        with open(tb.STATS_FILE, "r", encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise BotStateUnavailableError(
            f"файл состояния {tb.STATS_FILE!r} повреждён или временно недоступен"
        ) from exc
    if not isinstance(raw, dict):
        raise BotStateUnavailableError(f"файл состояния {tb.STATS_FILE!r} не содержит JSON-объект")
    tb.stats = tb.load_stats()
