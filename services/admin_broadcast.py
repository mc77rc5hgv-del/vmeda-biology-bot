"""Administrator-only media drafts. Nothing is sent to users before confirmation."""
import asyncio
import re
import secrets
from dataclasses import dataclass
from html import unescape

from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import InputMediaPhoto, InputMediaVideo
from aiogram.utils.keyboard import InlineKeyboardBuilder


@dataclass
class Draft:
    token: str
    text: str
    media: list


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


async def deliver(bot, chat_id, draft):
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


async def collect(tb, message, *, selected=False):
    """Cache out-of-order album parts, including parts preceding the command caption."""
    key = (message.chat.id, message.media_group_id)
    bucket = albums.setdefault(key, {'messages': {}, 'selected': False, 'task': None})
    bucket['messages'][message.message_id] = message
    bucket['selected'] |= selected
    if selected:
        bucket['admin'] = message.from_user.id
        bucket['message'] = message
    if bucket['task']:
        bucket['task'].cancel()

    async def flush():
        try:
            await asyncio.sleep(ALBUM_DELAY)
            albums.pop(key, None)
            if bucket['selected'] and tb.ADMIN_PENDING.get(bucket['admin'], {}).get('action') == 'broadcast_content':
                await preview(tb, bucket['message'], list(bucket['messages'].values()))
        except asyncio.CancelledError:
            pass
        except Exception:
            tb.logger.exception('Broadcast album preview failed')

    bucket['task'] = asyncio.create_task(flush())


async def receive(tb, message, *, command=False):
    admin_id = message.from_user.id
    if not tb.is_admin(admin_id):
        return False
    selected = command or tb.ADMIN_PENDING.get(admin_id, {}).get('action') == 'broadcast_content'
    if selected:
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
    if not tb.is_admin(admin_id):
        await callback.answer('Нет доступа', show_alert=True)
        return
    token = callback.data.split(':', 1)[1]
    draft = drafts.get(admin_id)
    if not draft or draft.token != token:
        await callback.answer('Этот предпросмотр уже неактуален.', show_alert=True)
        return
    if busy:
        await callback.answer('Дождись завершения текущей рассылки.', show_alert=True)
        return
    busy = True
    try:
        status = await callback.message.answer('⏳ Рассылка запущена…')
    except Exception:
        busy = False
        raise
    drafts.pop(admin_id, None)
    task = asyncio.create_task(send_all(tb, status, draft, tuple(tb.stats['total_users'])))
    jobs.add(task)
    task.add_done_callback(jobs.discard)
    await callback.answer('Рассылка запущена')


async def cancel(tb, callback):
    if not tb.is_admin(callback.from_user.id):
        await callback.answer('Нет доступа', show_alert=True)
        return
    draft = drafts.get(callback.from_user.id)
    if draft and draft.token == callback.data.split(':', 1)[1]:
        drafts.pop(callback.from_user.id, None)
        await callback.answer('Рассылка отменена')
    else:
        await callback.answer('Этот предпросмотр уже неактуален.')
