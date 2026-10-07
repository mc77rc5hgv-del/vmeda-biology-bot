"""Mocked Telegram delivery; isolated statistics from _bootstrap."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from _bootstrap import tb
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendPhoto
from aiogram.types import Message
from services import admin_broadcast as b

ADMIN = next(iter(tb.ADMIN_IDS))


def message(mid, *, kind=None, caption=None, group=None, user=ADMIN, text=None):
    data = dict(message_id=mid, date=1700000000, chat={'id':user,'type':'private'},
                from_user={'id':user,'is_bot':False,'first_name':'Admin'}, media_group_id=group)
    if text is not None:
        data['text'] = text
    if kind == 'photo':
        data['photo'] = [{'file_id':f'photo-{mid}', 'file_unique_id':str(mid),'width':100,'height':100}]
    if kind == 'video':
        data['video'] = {'file_id':f'video-{mid}','file_unique_id':str(mid),'width':100,'height':100,'duration':1}
    if caption:
        data['caption'] = caption
    return Message.model_validate(data)


async def main():
    mocked = SimpleNamespace(send_message=AsyncMock(),send_photo=AsyncMock(),send_video=AsyncMock(),send_media_group=AsyncMock())
    tb.bot = mocked
    b.ALBUM_DELAY = 0.01
    b.drafts.clear(); b.albums.clear(); tb.ADMIN_PENDING.clear()
    original = copy.deepcopy(tb.stats)
    # Photo and video captions remain attached; no extra text message to recipients.
    photo = b.build_draft([message(1,kind='photo',caption='Фото & текст')])
    await b.deliver(mocked,10,photo)
    assert mocked.send_photo.await_args.args == (10,'photo-1')
    assert mocked.send_photo.await_args.kwargs['caption'] == 'Фото &amp; текст'
    assert not mocked.send_message.called
    video = b.build_draft([message(2,kind='video',caption='/broadcast Видео')])
    await b.deliver(mocked,10,video)
    assert mocked.send_video.await_args.kwargs['caption'] == 'Видео'
    mixed = b.build_draft([message(4,kind='video'),message(3,kind='photo',caption='/broadcast Альбом')])
    await b.deliver(mocked,10,mixed)
    assert [m.type for m in mocked.send_media_group.await_args.kwargs['media']] == ['photo','video']
    assert mixed.media[0].caption == 'Альбом'
    assert mixed.media[1].caption is None
    # Reject excessive UTF-16 captions before sending; keep the draft editable.
    try:
        b.build_draft([message(1,kind='photo',caption='🙂'*513)])
        raise AssertionError('Oversized caption accepted')
    except ValueError:
        pass
    # A part arriving before the command caption is still included, exactly once.
    previews = []
    async def capture(tb_,source,messages,override=None):
        previews.append(b.build_draft(messages,override))
    with patch.object(b,'preview',capture):
        assert not await b.receive(tb,message(8,kind='video',group='album'))
        await b.receive(tb,message(7,kind='photo',caption='/broadcast Подпись',group='album'),command=True)
        await b.receive(tb,message(8,kind='video',group='album'))
        await asyncio.sleep(0.03)
        assert len(previews)==1 and len(previews[0].media)==2
        assert previews[0].media[0].caption=='Подпись'
        await b.receive(tb,message(9,kind='photo',caption='/broadcast Отмена',group='cancel'),command=True)
        tb.ADMIN_PENDING.pop(ADMIN,None)
        await asyncio.sleep(0.03)
        assert len(previews)==1
    # Non-admin commands/callbacks never send or obtain a draft.
    outsider = 987654321
    assert not await b.receive(tb,message(10,kind='photo',user=outsider),command=True)
    assert outsider not in b.drafts and outsider not in tb.ADMIN_PENDING
    status=SimpleNamespace(answer=AsyncMock())
    cb=SimpleNamespace(from_user=SimpleNamespace(id=outsider),data='admin_broadcast_go:x',message=status,answer=AsyncMock())
    await b.confirm(tb,cb)
    assert cb.answer.await_args.kwargs['show_alert'] is True
    # Rate limits retry the same recipient; failures never remove users/data.
    tb.stats['total_users']={111,222}; before=copy.deepcopy(tb.stats)
    attempts=[]
    async def simulated(bot,uid,draft):
        attempts.append(uid)
        if uid==111 and attempts.count(uid)==1:
            raise TelegramRetryAfter(method=SendPhoto(chat_id=uid,photo='photo'),message='Retry',retry_after=0)
        if uid==222:
            raise RuntimeError('Blocked bot')
    edit=AsyncMock()
    async def no_delay(_):pass
    with patch.object(b,'deliver',simulated),patch.object(b.asyncio,'sleep',no_delay),patch.object(tb,'safe_edit_text',edit),patch.object(tb,'save_stats',Mock()) as persisted:
        await b.send_all(tb,status,photo,(111,222))
        persisted.assert_called_once()
    assert attempts==[111,111,222]
    assert 'Доставлено: 1' in edit.await_args.args[1]
    assert 'Не доставлено: 1' in edit.await_args.args[1]
    before['broadcast_count']=before.get('broadcast_count',0)+1
    assert tb.stats==before
    # Confirmation consumes only this admin's token; a duplicate cannot send twice.
    b.drafts[ADMIN]=photo
    cb.from_user.id=ADMIN;cb.data='admin_broadcast_go:'+photo.token
    done=AsyncMock()
    with patch.object(b,'send_all',done):
        await b.confirm(tb,cb)
        await b.confirm(tb,cb)
        await asyncio.gather(*b.jobs)
        assert done.await_count==1
    b.busy=False
    tb.stats.clear();tb.stats.update(original)
    print('ALL ADMIN MEDIA BROADCAST TESTS PASSED')


asyncio.run(main())
