import asyncio
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import learning
from ..deps import get_current_user_id, get_fresh_bot_module
from .subjects import _anatomy_exam_question_by_num, _anatomy_exam_public_question, ANATOMY_EXAM_OPTION_LETTERS

router = APIRouter(prefix='/api/v1/anatomy/exam', tags=['anatomy'])


class Start(BaseModel):
    kind: str = 'part'
    part_id: int | None = None
    rating: bool = False


class Answer(BaseModel):
    position: int = Field(ge=0)
    selected_index: int = Field(ge=0, le=4)


class Preferences(BaseModel):
    rating: bool


@router.get('/preferences')
def preferences(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    return {'rating': tb.get_anatomy_exam_test_mode(user_id) == 'rating'}


@router.post('/preferences')
async def set_preferences(body: Preferences, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    tb.set_anatomy_exam_test_mode(user_id, 'rating' if body.rating else 'normal')
    return {'rating': body.rating}


def _public(tb, run):
    if not run:
        return None
    return {**run, 'questions': [_anatomy_exam_public_question(_anatomy_exam_question_by_num(tb, n)) for n in run['queue']]}


@router.post('/runs')
async def start(body: Start, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    if body.kind == 'part':
        part = next((p for p in tb.ANATOMY_EXAM_TEST_PARTS if p['id'] == body.part_id), None)
        if part is None:
            raise HTTPException(status_code=404, detail='Часть не найдена')
        nums = [q['num'] for q in part['questions']]
    elif body.kind == 'flash':
        pool = [q['num'] for p in tb.ANATOMY_EXAM_TEST_PARTS for q in p['questions']]
        nums = random.sample(pool, min(50, len(pool)))
    elif body.kind == 'mistakes':
        nums = await asyncio.to_thread(learning.get_anatomy_mistakes, user_id)
        if not nums:
            raise HTTPException(status_code=409, detail='Ошибок для повторения нет')
    else:
        raise HTTPException(status_code=422, detail='Неизвестный режим')
    run = await asyncio.to_thread(learning.create_anatomy_run, user_id, 'miniapp', body.kind, body.rating and body.kind == 'part', nums)
    return _public(tb, run)


@router.get('/runs/active')
async def active(user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    return _public(tb, await asyncio.to_thread(learning.active_anatomy_run, user_id))


@router.get('/runs/{run_id}')
async def get(run_id: str, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    return _public(tb, await asyncio.to_thread(learning.get_anatomy_run, user_id, run_id))


@router.post('/runs/{run_id}/answer')
async def answer(run_id: str, body: Answer, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    run = await asyncio.to_thread(learning.get_anatomy_run, user_id, run_id)
    if body.position >= len(run['queue']):
        raise HTTPException(status_code=409, detail='Вопрос устарел')
    question = _anatomy_exam_question_by_num(tb, run['queue'][body.position])
    letters = [letter for letter in ANATOMY_EXAM_OPTION_LETTERS if letter in question['options']]
    if body.selected_index >= len(letters):
        raise HTTPException(status_code=422, detail='Некорректный вариант')
    correct_index = letters.index(question['correct'])
    await asyncio.to_thread(learning.answer_anatomy_run, user_id, run_id, body.position, question['num'], letters[body.selected_index], body.selected_index == correct_index)
    return {'correct': body.selected_index == correct_index, 'correct_index': correct_index,
            'correct_letter': question['correct'], 'correct_text': question['options'][question['correct']],
            'explanation': tb.ANATOMY_EXAM_TEST_EXPLANATIONS.get(str(question['num']), '')}


@router.get('/mistakes')
async def mistakes(user_id: int = Depends(get_current_user_id)):
    return await asyncio.to_thread(learning.get_anatomy_mistakes, user_id)


@router.get('/ratings/{kind}')
async def ratings(kind: str, user_id: int = Depends(get_current_user_id), tb=Depends(get_fresh_bot_module)):
    if kind not in {'part', 'flash'}:
        raise HTTPException(status_code=404, detail='Рейтинг не найден')
    from services.anatomy_sync import scores
    result = await asyncio.to_thread(scores, tb, kind, user_id)
    def order(item):
        row = item[1]
        if kind == 'part':
            return row['correct'], row['correct']/row['total'] if row['total'] else 0
        return row['best_correct']/row['best_total'] if row['best_total'] else 0, row['best_correct']
    ranked = sorted(result.items(), key=order, reverse=True)
    own_rank = next((i+1 for i, (uid, _) in enumerate(ranked) if uid == str(user_id)), None)
    return {'own_rank': own_rank, 'entries': [{'rank': i+1, 'name': tb.donor_display_name(uid), **row} for i, (uid, row) in enumerate(ranked[:100])]}
