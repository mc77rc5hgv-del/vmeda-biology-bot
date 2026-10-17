"""Audit only: execute unmodified callback functions with simulated Telegram failures.
No bot credentials, polling, real Telegram requests, subscriptions or DB writes.
"""
from __future__ import annotations
import ast
import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DeleteDenied(RuntimeError):
    pass


def extract(path, name, environment):
    source = ast.parse((ROOT / path).read_text())
    node = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    line = node.lineno
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), path, 'exec'), environment)  # noqa: S102 - trusted source AST, isolated audit stubs
    return environment[name], line


async def main():
    cases = [
        ('handlers/anatomy.py', 'send_anatomy_album', ([{'path':'test.jpg'}], 0, 'test', 'test', 'test'),
         {'anatomy_page_count':lambda _:1, 'ANATOMY_ALBUM_PAGE_SIZE':10}),
        ('handlers/anatomy.py', 'cb_anatomy_exam_practice_question', (),
         {'get_anatomy_exam_practice_section':lambda _: {'questions':[{'num':1,'images':[{}]}]},
          'get_anatomy_exam_practice_question_text':lambda *_:'test', 'get_anatomy_exam_practice_question_keyboard':lambda *_:None}),
        ('handlers/histology.py', 'render_histology_image', ('diag','spec',0),
         {'get_histology_specimen':lambda *_:{'images':['test.png'],'title':'test','number':1},
          'get_histology_image_keyboard':lambda *_:None}),
        ('handlers/histology.py', 'render_histology_guess_question', (1,),
         {'get_histology_specimen':lambda *_:{'guess_image':'test.png'},
          'HISTOLOGY_GUESS_SESSIONS':{1:{'items':[('diag','spec')],'index':0,'scope':'all'}}}),
        ('handlers/physiology.py', 'send_rk_page', ({'control_id':'test'},0,[{'kind':'image','path':'test.png'}]),
         {'get_rk_page_keyboard':lambda *_:None}),
        ('handlers/operative_surgery.py', 'send_oh_instrument_album', ({'items':[{}]},0,0),
         {'oh_instrument_page_count':lambda _:1,'OH_INSTR_ALBUM_PAGE_SIZE':10}),
        ('handlers/mugs.py', 'cb_mugs_model', (),
         {'MUG_MODELS':{'test':{}},'get_mug_order_request_key':lambda *_:'test:1','_has_confirmed_order':lambda *_:False}),
    ]
    findings=[]
    for path, name, args, extra in cases:
        message = SimpleNamespace(delete=AsyncMock(side_effect=DeleteDenied("message can't be deleted for everyone")),
            answer=AsyncMock(), answer_photo=AsyncMock(), answer_media_group=AsyncMock())
        data = 'anatomy_exam_practice_q:1:1' if name == 'cb_anatomy_exam_practice_question' else 'mugs_model:test'
        callback = SimpleNamespace(data=data,message=message,from_user=SimpleNamespace(id=1),answer=AsyncMock())
        environment={'os':os,'FSInputFile':lambda path:path,
            'tb':SimpleNamespace(HISTOLOGY_IMAGES_DIR='/synthetic',MUG_PREORDER_ENABLED=True,stats={'mug_order_requests':{}}),**extra}
        func,line = extract(path,name,environment)
        try:
            await func(callback,*args)
        except DeleteDenied:
            delivered=message.answer.await_count+message.answer_photo.await_count+message.answer_media_group.await_count
            findings.append({'file':path,'line':line,'function':name,'delete_denial_aborts_navigation':True,'replacement_messages_sent':delivered})
        else:
            findings.append({'file':path,'line':line,'function':name,'delete_denial_aborts_navigation':False})
    result={'audited_commit':'2d207af072cc0603c7e93b609afefe1dd1a9c07c','synthetic_only':True,'findings':findings}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    (ROOT/'audit_checks/result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(1 if any(f['delete_denial_aborts_navigation'] for f in findings) else 0)


asyncio.run(main())
