"""Administrator-only media drafts. Nothing is sent to users before confirmation."""
import asyncio
import re
import secrets
from dataclasses import dataclass, replace
from html import unescape

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
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


def without_command(text):
    return re.sub(r'^/broadcast(?:@[A-Za-z0-9_]+)?(?:\s+|$)', '', text or '', count=1).strip()


def visible_length(text):
    return len(unescape(re.sub(r'<[^>]*>', '', text)).encode('utf-16-le')) // 2


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
    if draft.reply_markup is not None:
        messages = []
        if len(draft.media) > 1:
            messages = await _preset_request(bot.send_media_group, chat_id, media=draft.media)
        elif draft.media:
            item = draft.media[0]
            method = bot.send_photo if isinstance(item, InputMediaPhoto) else bot.send_video
            messages = [await _preset_request(method, chat_id, item.media, caption=item.caption, parse_mode='HTML')]
        await _preset_request(bot.send_message, chat_id, draft.text, parse_mode='HTML',
                              reply_markup=draft.reply_markup, disable_web_page_preview=True)
        return messages
    if len(draft.media) > 1:
        return await bot.send_media_group(chat_id, media=draft.media)
    if draft.media:
        item = draft.media[0]
        if isinstance(item, InputMediaPhoto):
            return await bot.send_photo(chat_id, item.media, caption=item.caption, parse_mode='HTML')
        return await bot.send_video(chat_id, item.media, caption=item.caption, parse_mode='HTML')
    return await bot.send_message(chat_id, draft.text, parse_mode='HTML')


async def preview(tb, message, messages, override=None):
    admin_id = message.from_user.id
    if not tb.is_admin(admin_id):
        return
    try:
        draft = build_draft(messages, override)
        await deliver(tb.bot, message.chat.id, draft)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    except Exception:
        tb.logger.exception('Broadcast preview failed')
        await message.answer('Не удалось показать предпросмотр. Рассылка не отправлена; попробуй ещё раз.')
        return
    drafts[admin_id] = draft
    tb.ADMIN_PENDING.pop(admin_id, None)
    keyboard = InlineKeyboardBuilder()
    keyboard.button(text='✅ Отправить всем', callback_data='admin_broadcast_go:' + draft.token)
    keyboard.button(text='❌ Отмена', callback_data='admin_broadcast_cancel:' + draft.token)
    keyboard.adjust(1)
    await message.answer(
        f'👆 Предпросмотр рассылки. Получателей: {len(tb.stats["total_users"])}.\n'
        'Фото и видео отправятся с подписью; несколько файлов — одним альбомом.',
        reply_markup=keyboard.as_markup(),
    )


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
        builder.button(text='Добавить фото или видео', callback_data=f'admin_broadcast_edit:media:{draft.token}')
        if draft.media:
            builder.button(text='Удалить вложения', callback_data=f'admin_broadcast_edit:clear:{draft.token}')
        builder.button(text='❌ Отмена', callback_data='admin_broadcast_cancel:' + draft.token)
        builder.adjust(1)
        await message.answer(
            f'Предпросмотр анонса · получателей: {len(tb.stats["total_users"])}\n'
            f'Вложений: {len(draft.media)} из 10. Кнопки анонса сохраняются при редактировании.',
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
    admin_id = callback.from_user.id
    action, _, token = callback.data.removeprefix('admin_broadcast_edit:').partition(':')
    draft = drafts.get(admin_id)
    if not can_confirm(tb, admin_id, draft):
        await callback.answer('Нет доступа', show_alert=True)
        return
    if (not draft or draft.reply_markup is None or draft.token != token
            or getattr(getattr(callback.message, 'chat', None), 'type', None) != 'private'):
        await callback.answer('Открой актуальный предпросмотр в личном чате с ботом.', show_alert=True)
        return
    if tb.ADMIN_PENDING.get(admin_id, {}).get('action') == 'broadcast_preview':
        await callback.answer('Дождись предпросмотра.', show_alert=True)
        return
    if action in ('back', 'clear'):
        previous = tb.ADMIN_PENDING.get(admin_id)
        updated = replace(draft, token=secrets.token_hex(8), media=[] if action == 'clear' else draft.media)
        await callback.answer()
        if drafts.get(admin_id) is draft and tb.ADMIN_PENDING.get(admin_id) is previous:
            await preview_preset(tb, callback.message, updated, admin_id)
        return
    if action not in ('text', 'media'):
        await callback.answer()
        return
    pending = {'action': 'broadcast_edit', 'mode': action, 'draft': draft}
    tb.ADMIN_PENDING[admin_id] = pending
    builder = InlineKeyboardBuilder()
    builder.button(text='Назад к предпросмотру', callback_data=f'admin_broadcast_edit:back:{token}')
    await callback.answer()
    if tb.ADMIN_PENDING.get(admin_id) is pending:
        prompt = ('Пришли новый текст одним сообщением. Telegram-форматирование сохранится.'
                  if action == 'text' else 'Пришли фото, видео или альбом. Всего можно прикрепить до 10 файлов.')
        await callback.message.answer(prompt, reply_markup=builder.as_markup())


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
        updated = replace(draft, token=secrets.token_hex(8), text=updated_text)
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
