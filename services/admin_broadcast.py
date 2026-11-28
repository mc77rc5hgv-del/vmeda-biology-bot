"""Administrator-only media drafts. Nothing is sent to users before confirmation."""
import asyncio
import re
import secrets
from dataclasses import dataclass, replace
from html import unescape
from urllib.parse import urlsplit

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from aiogram.utils.keyboard import InlineKeyboardBuilder


@dataclass
class Draft:
    token: str
    text: str
    media: list
    reply_markup: InlineKeyboardMarkup | None = None
    allow_payment_admin: bool = False


drafts: dict[int, Draft] = {}
albums: dict[tuple, dict] = {}
jobs: set = set()
busy = False
ALBUM_DELAY = 1.5
BUTTON_LIMIT = 12


def without_command(text):
    return re.sub(r'^/broadcast(?:@[A-Za-z0-9_]+)?(?:\s+|$)', '', text or '', count=1).strip()


def visible_length(text):
    return len(unescape(re.sub(r'<[^>]*>', '', text)).encode('utf-16-le')) // 2


def parse_buttons(raw):
    from services.study_announcements import QUICK_ACTIONS

    rows = []
    if raw.strip().casefold() == 'без кнопок':
        return None
    for line in raw.splitlines():
        if not line.strip():
            continue
        label, _, target = line.partition('|')
        label, target = label.strip(), target.strip()
        if not label or not target or len(label) > 64:
            raise ValueError('Укажи каждую кнопку в формате «Название | Ссылка или действие». Название — до 64 символов.')
        action = QUICK_ACTIONS.get(target.casefold())
        if action:
            button = InlineKeyboardButton(text=label, callback_data=action)
        else:
            try:
                url = urlsplit(target)
                valid = url.scheme == 'https' and url.hostname and not url.username and not url.password
                _ = url.port
            except ValueError:
                valid = False
            if not valid or any(char.isspace() or ord(char) < 32 for char in target) or '\\' in target:
                raise ValueError('Укажи полную HTTPS-ссылку или одно из действий VMEDA из подсказки.')
            button = InlineKeyboardButton(text=label, url=target)
        rows.append([button])
    if not 1 <= len(rows) <= BUTTON_LIMIT:
        raise ValueError(f'Добавь от 1 до {BUTTON_LIMIT} кнопок или напиши «без кнопок».')
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_draft(messages, override=None):
    media = []
    text = ''
    for message in sorted(messages, key=lambda m: m.message_id):
        caption = without_command(message.html_text)
        if message.photo or message.video:
            if override is not None:
                caption = override if not media else ''
            if visible_length(caption) > 1024:
                raise ValueError('Подпись к фото или видео должна быть не длиннее 1024 символов.')
            cls = InputMediaPhoto if message.photo else InputMediaVideo
            file_id = message.photo[-1].file_id if message.photo else message.video.file_id
            media.append(cls(media=file_id, caption=caption or None, parse_mode='HTML'))
        else:
            text = override if override is not None else caption
    if not media and not text:
        raise ValueError('Пришли текст, фото или видео с подписью.')
    if len(media) > 10:
        raise ValueError('В альбоме может быть не больше 10 фото и видео.')
    if not media and visible_length(text) > 4096:
        raise ValueError('Текст сообщения должен быть не длиннее 4096 символов.')
    return Draft(secrets.token_hex(8), text, media)


async def _preset_request(method, *args, **kwargs):
    # Retry just the throttled stage, never an already delivered photo album.
    try:
        return await method(*args, **kwargs)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 0.1)
        try:
            return await method(*args, **kwargs)
        except TelegramRetryAfter as retry:
            raise RuntimeError('Preset rate limit persists; no album replay') from retry


async def deliver(bot, chat_id, draft):
    separate_text = bool(draft.media and (draft.text or (len(draft.media) > 1 and draft.reply_markup)))
    request = _preset_request if separate_text else _direct_request
    messages = []
    if len(draft.media) > 1:
        messages = await request(bot.send_media_group, chat_id, media=draft.media)
    elif draft.media:
        item = draft.media[0]
        send_media = bot.send_photo if isinstance(item, InputMediaPhoto) else bot.send_video
        kwargs = {'reply_markup': draft.reply_markup} if draft.reply_markup and not separate_text else {}
        messages = [await request(send_media, chat_id, item.media, caption=item.caption, parse_mode='HTML', **kwargs)]
    if separate_text or not draft.media:
        kwargs = {'reply_markup': draft.reply_markup, 'disable_web_page_preview': True} if draft.reply_markup else {}
        method = _preset_request if separate_text or draft.reply_markup else _direct_request
        await method(bot.send_message, chat_id, draft.text or 'Открыть ссылки', parse_mode='HTML', **kwargs)
    return messages


async def _direct_request(method, *args, **kwargs):
    return await method(*args, **kwargs)


async def preview(tb, message, messages, override=None):
    admin_id = message.from_user.id
    if not tb.is_admin(admin_id):
        return
    try:
        draft = build_draft(messages, override)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await preview_preset(tb, message, draft, admin_id)


def can_confirm(tb, admin_id, draft=None):
    return tb.is_admin(admin_id) or bool(draft and draft.allow_payment_admin and tb.is_payment_admin(admin_id))


async def preview_text_preset(tb, callback, text, keyboard):
    user_id = callback.from_user.id
    if not (tb.is_admin(user_id) or tb.is_payment_admin(user_id)):
        await callback.answer('Нет доступа', show_alert=True)
        return
    if getattr(getattr(callback.message, 'chat', None), 'type', None) != 'private':
        await callback.answer('Открой анонс в личном чате с ботом.', show_alert=True)
        return
    await callback.answer()
    draft = Draft(secrets.token_hex(8), text(), [], reply_markup=keyboard(), allow_payment_admin=True)
    await preview_preset(tb, callback.message, draft, user_id)


async def preview_preset(tb, message, draft, admin_id):
    if not can_confirm(tb, admin_id, draft):
        return False
    previous = tb.ADMIN_PENDING.get(admin_id)
    pending = {'action': 'broadcast_preview'}
    tb.ADMIN_PENDING[admin_id] = pending
    try:
        sent = await deliver(tb.bot, message.chat.id, draft)
        # Reuse Telegram's file IDs for preset uploads. Attachments from chat already have IDs.
        cached = []
        for item, delivered in zip(draft.media, sent, strict=True):
            if not isinstance(item.media, str):
                file_id = delivered.photo[-1].file_id if isinstance(item, InputMediaPhoto) else delivered.video.file_id
                item = item.model_copy(update={'media': file_id})
            cached.append(item)
        draft.media = cached
        if tb.ADMIN_PENDING.get(admin_id) is not pending:
            return False
        builder = InlineKeyboardBuilder()
        builder.button(text='✅ Отправить всем', callback_data='admin_broadcast_go:' + draft.token)
        builder.button(text='Редактировать текст', callback_data=f'admin_broadcast_edit:text:{draft.token}')
        if tb.is_admin(admin_id):
            builder.button(text='Настроить кнопки' if draft.reply_markup else 'Добавить кнопки',
                           callback_data=f'admin_broadcast_edit:buttons:{draft.token}')
        builder.button(text='Добавить фото или видео', callback_data=f'admin_broadcast_edit:media:{draft.token}')
        if draft.media:
            builder.button(text='Удалить вложения', callback_data=f'admin_broadcast_edit:clear:{draft.token}')
        builder.button(text='❌ Отмена', callback_data='admin_broadcast_cancel:' + draft.token)
        builder.adjust(1)
        button_count = sum(map(len, draft.reply_markup.inline_keyboard)) if draft.reply_markup else 0
        await message.answer(
            f'Предпросмотр анонса · получателей: {len(tb.stats["total_users"])}\n'
            f'Кнопок: {button_count} · Вложений: {len(draft.media)} из 10',
            reply_markup=builder.as_markup(),
        )
    except Exception:
        tb.logger.exception('Preset broadcast preview failed')
        if tb.ADMIN_PENDING.get(admin_id) is pending:
            if previous is None:
                tb.ADMIN_PENDING.pop(admin_id, None)
            else:
                tb.ADMIN_PENDING[admin_id] = previous
            await message.answer('Не удалось показать предпросмотр. Попробуй ещё раз.')
        return False
    if tb.ADMIN_PENDING.get(admin_id) is not pending:
        return False
    drafts[admin_id] = draft
    tb.ADMIN_PENDING.pop(admin_id, None)
    return True


async def edit(tb, callback):
    from services.study_announcements import QUICK_ACTIONS

    admin_id = callback.from_user.id
    action, _, token = callback.data.removeprefix('admin_broadcast_edit:').partition(':')
    draft = drafts.get(admin_id)
    if not can_confirm(tb, admin_id, draft):
        await callback.answer('Нет доступа', show_alert=True)
        return
    if (not draft or draft.token != token
            or getattr(getattr(callback.message, 'chat', None), 'type', None) != 'private'):
        await callback.answer('Открой актуальный предпросмотр в личном чате с ботом.', show_alert=True)
        return
    if tb.ADMIN_PENDING.get(admin_id, {}).get('action') == 'broadcast_preview':
        await callback.answer('Дождись предпросмотра.', show_alert=True)
        return
    if action in ('back', 'clear'):
        if action == 'clear' and not draft.text.strip():
            await callback.answer('Сначала добавь текст, чтобы анонс не оказался пустым.', show_alert=True)
            return
        previous = tb.ADMIN_PENDING.get(admin_id)
        updated = replace(draft, token=secrets.token_hex(8), media=[] if action == 'clear' else draft.media)
        await callback.answer()
        if drafts.get(admin_id) is draft and tb.ADMIN_PENDING.get(admin_id) is previous:
            await preview_preset(tb, callback.message, updated, admin_id)
        return
    if action == 'buttons' and not tb.is_admin(admin_id):
        await callback.answer('Нет доступа', show_alert=True)
        return
    if action not in ('text', 'media', 'buttons'):
        await callback.answer()
        return
    pending = {'action': 'broadcast_edit', 'mode': action, 'draft': draft}
    tb.ADMIN_PENDING[admin_id] = pending
    builder = InlineKeyboardBuilder()
    builder.button(text='Назад к предпросмотру', callback_data=f'admin_broadcast_edit:back:{token}')
    await callback.answer()
    if tb.ADMIN_PENDING.get(admin_id) is pending:
        prompts = {
            'text': 'Пришли новый текст одним сообщением. Telegram-форматирование сохранится.',
            'media': 'Пришли фото, видео или альбом. Всего можно прикрепить до 10 файлов.',
            'buttons': (
                f'<b>Кнопки анонса</b>\n\nПришли до {BUTTON_LIMIT} строк в одном сообщении. '
                'Новый список заменит текущий. Кнопки появятся в порядке строк.\n\n'
                '<code>Оплатить тесты | тесты</code>\n'
                '<code>Открыть материалы | https://example.com</code>\n\n'
                'Действия VMEDA\n'
                + ', '.join(f'<code>{key}</code>' for key in QUICK_ACTIONS)
                + '\n\n<code>без кнопок</code> удалит все кнопки.'
            ),
        }
        await callback.message.answer(prompts[action], parse_mode='HTML', reply_markup=builder.as_markup())


async def apply_edit(tb, message, messages, pending):
    admin_id = message.from_user.id
    draft = pending['draft']
    if (tb.ADMIN_PENDING.get(admin_id) is not pending or drafts.get(admin_id) is not draft
            or not can_confirm(tb, admin_id, draft)):
        return
    if pending['mode'] == 'text':
        updated_text = (message.html_text or '').strip() if message.text else ''
        if not updated_text or visible_length(updated_text) > 4096:
            await message.answer('Пришли текст одним сообщением, до 4096 символов.')
            return
        media = draft.media
        if media and not draft.text:
            caption = updated_text if visible_length(updated_text) <= 1024 else None
            media = [media[0].model_copy(update={'caption': caption}), *media[1:]]
            if caption:
                updated_text = ''
        updated = replace(draft, token=secrets.token_hex(8), text=updated_text, media=media)
    elif pending['mode'] == 'buttons':
        if not tb.is_admin(admin_id):
            return
        try:
            markup = parse_buttons(message.text or '')
        except ValueError as exc:
            await message.answer(str(exc))
            return
        updated = replace(draft, token=secrets.token_hex(8), reply_markup=markup)
    else:
        if not all(item.photo or item.video for item in messages):
            await message.answer('Пришли фото, видео или альбом.')
            return
        if len(draft.media) + len(messages) > 10:
            await message.answer(f'В анонсе уже {len(draft.media)} вложений. Лимит — 10. Лишние файлы не добавлены.')
            return
        try:
            attached = build_draft(messages).media
        except ValueError as exc:
            await message.answer(str(exc))
            return
        updated = replace(draft, token=secrets.token_hex(8), media=[*draft.media, *attached])
    await preview_preset(tb, message, updated, admin_id)


async def collect(tb, message, *, selected=False):
    """Cache out-of-order album parts, including parts preceding the command caption."""
    key = (message.chat.id, message.media_group_id)
    bucket = albums.setdefault(key, {'messages': {}, 'selected': False, 'task': None})
    bucket['messages'][message.message_id] = message
    bucket['selected'] |= selected
    if selected:
        bucket['admin'] = message.from_user.id
        bucket['message'] = message
        bucket['pending'] = tb.ADMIN_PENDING.get(message.from_user.id)
    if bucket['task']:
        bucket['task'].cancel()

    async def flush():
        try:
            await asyncio.sleep(ALBUM_DELAY)
            albums.pop(key, None)
            if bucket['selected'] and tb.ADMIN_PENDING.get(bucket['admin']) is bucket['pending']:
                messages = list(bucket['messages'].values())
                if bucket['pending']['action'] == 'broadcast_edit':
                    await apply_edit(tb, bucket['message'], messages, bucket['pending'])
                else:
                    await preview(tb, bucket['message'], messages)
        except asyncio.CancelledError:
            pass
        except Exception:
            tb.logger.exception('Broadcast album preview failed')

    bucket['task'] = asyncio.create_task(flush())


async def receive(tb, message, *, command=False):
    admin_id = message.from_user.id
    pending = tb.ADMIN_PENDING.get(admin_id, {})
    if not command and pending.get('action') == 'broadcast_edit':
        if message.chat.type != 'private' or not can_confirm(tb, admin_id, pending['draft']):
            return False
        if message.media_group_id and pending['mode'] == 'media':
            await collect(tb, message, selected=True)
        else:
            await apply_edit(tb, message, [message], pending)
        return True
    if not tb.is_admin(admin_id):
        return False
    selected = command or tb.ADMIN_PENDING.get(admin_id, {}).get('action') == 'broadcast_content'
    if command:
        drafts.pop(admin_id, None)
        tb.ADMIN_PENDING[admin_id] = {'action': 'broadcast_content'}
    if message.media_group_id:
        await collect(tb, message, selected=selected)
        return selected or albums.get((message.chat.id, message.media_group_id), {}).get('selected', False)
    if not selected:
        return False
    if command and message.reply_to_message:
        source = message.reply_to_message
        if source.media_group_id:
            await message.answer('Чтобы отправить весь альбом, нажми «Создать рассылку» и перешли туда все его фото и видео вместе.')
            return True
        await preview(tb, message, [source], without_command(message.html_text) or None)
    elif not message.photo and not message.video and not without_command(message.html_text):
        await message.answer('Пришли текст, фото, видео или альбом с подписью.\nДля отмены открой /admin.')
    else:
        await preview(tb, message, [message])
    return True


async def send_all(tb, status, draft, recipients):
    global busy
    sent = failed = 0
    try:
        for user_id in recipients:
            try:
                try:
                    await deliver(tb.bot, user_id, draft)
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after + 0.1)
                    await deliver(tb.bot, user_id, draft)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.06 * max(1, len(draft.media)))
        tb.stats['broadcast_count'] = tb.stats.get('broadcast_count', 0) + 1
        tb.save_stats()
        await tb.safe_edit_text(status, f'✅ Рассылка завершена\nДоставлено: {sent}\nНе доставлено: {failed}')
    except Exception:
        tb.logger.exception('Broadcast job failed')
        try:
            await status.answer(f'Рассылка прервана. Доставлено: {sent}; не доставлено: {failed}. Автоматический повтор не выполняется.')
        except Exception:
            tb.logger.exception('Broadcast status delivery failed')
    finally:
        busy = False


async def confirm(tb, callback):
    global busy
    admin_id = callback.from_user.id
    draft = drafts.get(admin_id)
    if not can_confirm(tb, admin_id, draft):
        await callback.answer('Нет доступа', show_alert=True)
        return
    token = callback.data.split(':', 1)[1]
    if not draft or draft.token != token:
        await callback.answer('Этот предпросмотр уже неактуален.', show_alert=True)
        return
    if tb.ADMIN_PENDING.get(admin_id, {}).get('action') in ('broadcast_edit', 'broadcast_preview'):
        await callback.answer('Заверши редактирование и открой новый предпросмотр.', show_alert=True)
        return
    if busy:
        await callback.answer('Дождись завершения текущей рассылки.', show_alert=True)
        return
    busy = True
    drafts.pop(admin_id, None)
    try:
        status = await callback.message.answer('⏳ Рассылка запущена…')
    except Exception:
        drafts.setdefault(admin_id, draft)
        busy = False
        raise
    task = asyncio.create_task(send_all(tb, status, draft, tuple(tb.stats['total_users'])))
    jobs.add(task)
    task.add_done_callback(jobs.discard)
    await callback.answer('Рассылка запущена')


async def cancel(tb, callback):
    draft = drafts.get(callback.from_user.id)
    if not can_confirm(tb, callback.from_user.id, draft):
        await callback.answer('Нет доступа', show_alert=True)
        return
    draft = drafts.get(callback.from_user.id)
    if draft and draft.token == callback.data.split(':', 1)[1]:
        drafts.pop(callback.from_user.id, None)
        if tb.ADMIN_PENDING.get(callback.from_user.id, {}).get('action') in ('broadcast_edit', 'broadcast_preview'):
            tb.ADMIN_PENDING.pop(callback.from_user.id, None)
        await callback.answer('Рассылка отменена')
    else:
        await callback.answer('Этот предпросмотр уже неактуален.')
