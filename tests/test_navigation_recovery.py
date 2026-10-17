"""Telegram navigation/media failure regressions, isolated bootstrap stats and mocked transport."""
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
from types import SimpleNamespace
from unittest.mock import Mock, patch

from _bootstrap import tb
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage
from handlers import anatomy, histology, physiology, operative_surgery, mugs, admin, dynamic_courses
from services.telegram_ui import escaped_text_pages


class SendFailed(RuntimeError):
    pass


class Message:
    def __init__(self, fail_send=False):
        self.fail_send = fail_send
        self.events = []
        self.sent = []

    async def delete(self):
        self.events.append('delete')
        raise TelegramBadRequest(DeleteMessage(chat_id=1, message_id=1), "message can't be deleted for everyone")

    async def deliver(self, kind, args, kwargs):
        self.events.append('send')
        if self.fail_send:
            raise SendFailed('synthetic delivery failure')
        self.sent.append((kind, args, kwargs))
        return SimpleNamespace(photo=[], chat=SimpleNamespace(id=1), message_id=2)

    async def answer(self, *args, **kwargs):
        return await self.deliver('text', args, kwargs)

    async def answer_photo(self, *args, **kwargs):
        return await self.deliver('photo', args, kwargs)

    async def answer_media_group(self, *args, **kwargs):
        return [await self.deliver('album', args, kwargs)]


class Callback:
    def __init__(self, data='test', fail_send=False, uid=1):
        self.data = data
        self.from_user = SimpleNamespace(id=uid)
        self.message = Message(fail_send)
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


def patched(stack, module, **values):
    for key, value in values.items():
        stack.enter_context(patch.object(module, key, value))


async def test_media_navigation():
    image = {'path':'synthetic.jpg','caption':'test','credit':'test'}
    cases = [
        (anatomy.send_anatomy_album, ([image], 0, 'test', 'test', 'test'), 'test'),
        (anatomy.send_anatomy_album, ([image, image], 0, 'test', 'test', 'test'), 'test'),
        (anatomy.cb_anatomy_exam_practice_question, (), 'anatomy_exam_practice_q:1:1'),
        (histology.render_histology_image, ('diag','spec',0), 'test'),
        (histology.render_histology_guess_question, (1,), 'test'),
        (physiology.send_rk_page, ({'control_id':'test','title':'test'},0,[{'kind':'image','path':'synthetic.jpg'}]), 'test'),
        (physiology.send_rk_page, ({'control_id':'test','title':'test'},0,[{'kind':'text','text':'test'}]), 'test'),
        (operative_surgery.send_oh_instrument_album, ({'group':'test','items':[{'name':'test'}]},0,0), 'test'),
        (mugs.cb_mugs_model, (), 'mugs_model:test'),
    ]
    for fail_send in (False, True):
        for func, args, data in cases:
            with ExitStack() as stack:
                patched(stack, anatomy, _anatomy_image_media=lambda _: 'synthetic-file-id',
                        _cache_anatomy_file_id=lambda *_: False,
                        get_anatomy_exam_practice_section=lambda _: {'questions':[{'num':1,'question':'test','images':[image]}]},
                        get_anatomy_exam_practice_question_text=lambda *_:'test')
                patched(stack, histology, get_histology_specimen=lambda *_:{'number':1,'title':'test','images':['test.jpg'],'guess_image':'test.jpg'},
                        HISTOLOGY_GUESS_SESSIONS={1:{'id':'synthetic','items':[('diag','spec')],'index':0,'scope':'all'}})
                patched(stack, physiology, _phys_rk_image_media=lambda _: 'synthetic-file-id', _cache_phys_rk_file_id=lambda *_:False)
                patched(stack, operative_surgery, _oh_instrument_image_media=lambda _: 'synthetic-file-id', _cache_oh_instrument_file_id=lambda *_:False)
                patched(stack, mugs, MUG_MODELS={'test':{}}, _has_confirmed_order=lambda *_:False,
                        get_mug_photo=lambda _: 'synthetic-file-id', get_mug_model_text=lambda *_:'test',
                        get_mug_model_keyboard=lambda *_:None, cache_mug_photo=lambda *_:False)
                stack.enter_context(patch.object(tb, 'MUG_PREORDER_ENABLED', True))
                callback = Callback(data, fail_send)
                try:
                    await func(callback, *args)
                except SendFailed:
                    assert fail_send
                else:
                    assert not fail_send
                if fail_send:
                    assert 'delete' not in callback.message.events, func.__name__
                else:
                    assert callback.message.sent and callback.message.events[0] == 'send'
                    assert callback.message.events[-1] == 'delete', func.__name__
    # Practice question album and long answer branches retain the same delivery order.
    for images, body in (([image,image],'test'), ([image],'A'*1400)):
        with ExitStack() as stack:
            patched(stack, anatomy, _anatomy_image_media=lambda _: 'synthetic-file-id', _cache_anatomy_file_id=lambda *_:False,
                    get_anatomy_exam_practice_section=lambda _: {'questions':[{'num':1,'question':'test','images':images}]},
                    get_anatomy_exam_practice_question_text=lambda *_:body)
            callback=Callback('anatomy_exam_practice_q:1:1')
            await anatomy.cb_anatomy_exam_practice_question(callback)
            assert len(callback.message.sent)==2 and callback.message.events[-1]=='delete'


async def test_saved_histology_answer_resumes_after_failed_delivery():
    session={'id':'recovery','items':[('diag','one'),('diag','two')], 'index':0,'displayed_index':0,
             'scope':'all','know':0,'dont_know':0}
    records=[]
    async def direct(fn,*args):
        return fn(*args)
    with ExitStack() as stack:
        patched(stack,histology,HISTOLOGY_GUESS_SESSIONS={1:session},_learning_call=direct,
                record_histology_result=lambda *args:records.append(args),get_histology_specimen=lambda *_:{'guess_image':'test.jpg'})
        callback=Callback('histology_guess_know:recovery:0',fail_send=True)
        try:
            await histology.cb_histology_guess_answer(callback)
        except SendFailed:
            pass
        else:
            raise AssertionError('Expected simulated transport failure')
        assert len(records)==1 and session['index']==1 and session['know']==1 and session['delivery_failed']
        callback.message.fail_send=False
        await histology.cb_histology_guess_answer(callback)
        assert len(records)==1 and session['index']==1 and not session['delivery_failed']
        assert len(callback.message.sent)==1
        await histology.cb_histology_guess_answer(callback)
        assert len(records)==1 and len(callback.message.sent)==1


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags=[]
    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


async def test_moderation_pages_and_permissions():
    raw='A < B & <sarcomere> "препарат" 🧠\n'*500
    parts=escaped_text_pages(raw)
    assert unescape(''.join(parts))==raw and all(len(p)<=3400 for p in parts)
    emoji_pages=escaped_text_pages('🧠'*5000)
    assert unescape(''.join(emoji_pages))=='🧠'*5000
    assert all(len(unescape(page).encode('utf-16-le'))//2<=3400 for page in emoji_pages)
    key='a'*24
    entry={'question_preview':'Объясни <sarcomere>', 'answer':raw,'subject':'biology','status':'pending'}
    snapshot=deepcopy(entry)
    pages=admin.get_ai_cache_queue_pages(entry)
    for index in range(len(pages)):
        text=admin.get_ai_cache_queue_text(key,entry,index)
        assert len(text)<3800
        parser=Tags()
        parser.feed(text)
        assert set(parser.tags)<={'b'}
        keyboard=admin.get_ai_cache_queue_keyboard(key,index,len(pages))
        assert all(len(button.callback_data.encode())<=64 for row in keyboard.inline_keyboard for button in row)
    assert entry==snapshot
    edits=[]
    async def edit(message,text,**kwargs):
        edits.append(text)
    with patch.object(tb,'safe_edit_text',edit), patch.dict(tb.stats['ai_answer_cache'],{key:entry}):
        callback=Callback(f'admin_ai_cache_page:{key}:1',uid=next(iter(tb.ADMIN_IDS)))
        await admin.cb_admin_ai_cache_page(callback)
        assert 'Страница 2/' in edits[-1]
        before=len(edits)
        callback.from_user.id=987654321
        await admin.cb_admin_ai_cache_page(callback)
        assert len(edits)==before and callback.answers[-1][1]['show_alert']
        callback.from_user.id=next(iter(tb.ADMIN_IDS))
        with patch.dict(entry,{'status':'approved'}):
            await admin.cb_admin_ai_cache_page(callback)
        assert len(edits)==before
    callback=Callback('noop')
    await dynamic_courses.cb_dynamic_page_indicator(callback)
    assert len(callback.answers)==1 and not callback.message.events


async def main():
    original=deepcopy(tb.stats)
    await test_media_navigation()
    await test_saved_histology_answer_resumes_after_failed_delivery()
    await test_moderation_pages_and_permissions()
    assert tb.stats==original
    print('Navigation: seven media flows, send-before-delete, transport recovery without duplicate stats, safe complete AI pages, admin permissions and noop: OK')


asyncio.run(main())
