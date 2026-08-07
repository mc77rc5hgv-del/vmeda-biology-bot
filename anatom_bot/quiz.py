"""In-Telegram study sessions: tests, flashcards, Latin terms, blitz and mistake drills.

Sessions live in memory only (a dropped session costs the student nothing but a re-start), but
completed ones are folded into the shared website state via progress.apply_session_result, so
studying here moves the same XP/streak/due-dates the site shows.

Sessions are swept by age on every start so an abandoned run can't pin memory forever — this bot
is sized for thousands of concurrent students.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import content
from progress import reward_key

SESSION_TTL_SECONDS = 3 * 3600
TEST_SESSION_SIZE = 10
BLITZ_SESSION_SIZE = 15
FLASH_SESSION_SIZE = 12
TERMS_SESSION_SIZE = 10
MISTAKES_SESSION_SIZE = 15

MODE_TITLES = {
    "test": "📝 Тест",
    "flash": "🃏 Флеш-карточки",
    "match": "🏛 Латинские термины",
    "mistakes": "❌ Работа над ошибками",
    "blitz": "⚡ Блиц",
}


@dataclass
class QuizSession:
    user_id: int
    mode: str
    items: list[dict[str, Any]]
    module_id: Optional[str] = None
    topic_num: Optional[int] = None
    topic_name: str = ""
    index: int = 0
    correct: int = 0
    wrong: list[dict[str, Any]] = field(default_factory=list)
    solved: list[str] = field(default_factory=list)
    reward_keys: list[str] = field(default_factory=list)
    revealed: bool = False
    started_at: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def finished(self) -> bool:
        return self.index >= len(self.items)

    def current(self) -> Optional[dict[str, Any]]:
        if self.finished:
            return None
        return self.items[self.index]


SESSIONS: dict[int, QuizSession] = {}


def _sweep() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    for user_id in [uid for uid, s in SESSIONS.items() if s.started_at < cutoff]:
        SESSIONS.pop(user_id, None)


def get_session(user_id: int) -> Optional[QuizSession]:
    return SESSIONS.get(user_id)


def end_session(user_id: int) -> Optional[QuizSession]:
    return SESSIONS.pop(user_id, None)


def start_test(
    user_id: int, module_id: Optional[str], topic_num: Optional[int], rng: Optional[random.Random] = None
) -> Optional[QuizSession]:
    _sweep()
    size = TEST_SESSION_SIZE if topic_num is not None or module_id else BLITZ_SESSION_SIZE
    items = content.sample_tests(module_id, topic_num, limit=size, rng=rng)
    if not items:
        return None

    name = content.topic_name(module_id, topic_num) if module_id and topic_num is not None else ""
    session = QuizSession(
        user_id=user_id,
        mode="test" if topic_num is not None else "blitz",
        items=items,
        module_id=module_id,
        topic_num=topic_num,
        topic_name=name,
    )
    SESSIONS[user_id] = session
    return session


def start_blitz(user_id: int, rng: Optional[random.Random] = None) -> Optional[QuizSession]:
    """Random questions drawn from the entire course — no single topic, so no bestPct is written."""
    _sweep()
    items = content.sample_tests(None, None, limit=BLITZ_SESSION_SIZE, rng=rng)
    if not items:
        return None
    session = QuizSession(
        user_id=user_id, mode="blitz", items=items, topic_name="Блиц по всему курсу"
    )
    SESSIONS[user_id] = session
    return session


def start_flash(
    user_id: int, module_id: str, topic_num: int, rng: Optional[random.Random] = None
) -> Optional[QuizSession]:
    _sweep()
    cards = content.sample_cards(module_id, topic_num, limit=FLASH_SESSION_SIZE, rng=rng)
    if not cards:
        return None
    session = QuizSession(
        user_id=user_id,
        mode="flash",
        items=cards,
        module_id=module_id,
        topic_num=topic_num,
        topic_name=content.topic_name(module_id, topic_num),
    )
    SESSIONS[user_id] = session
    return session


def start_terms(
    user_id: int,
    module_id: Optional[str] = None,
    topic_num: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> Optional[QuizSession]:
    """Latin term -> meaning, as multiple choice. Distractors come from the whole course so that
    a small topic still yields four plausible options."""
    _sweep()
    rng = rng or random
    picks = content.sample_pairs(module_id, topic_num, limit=TERMS_SESSION_SIZE, rng=rng)
    if not picks:
        return None

    pool = content.all_pairs()
    items = [content.build_pair_question(pair, pool, rng) for pair in picks]
    session = QuizSession(
        user_id=user_id,
        mode="match",
        items=items,
        module_id=module_id,
        topic_num=topic_num,
        topic_name=(
            content.topic_name(module_id, topic_num)
            if module_id and topic_num is not None
            else "Латинские термины"
        ),
    )
    SESSIONS[user_id] = session
    return session


def start_mistakes(
    user_id: int, state: dict[str, Any], rng: Optional[random.Random] = None
) -> Optional[QuizSession]:
    """Re-ask the questions this student previously got wrong (site and bot share the list)."""
    _sweep()
    rng = rng or random
    stored = [m for m in (state.get("mistakes") or []) if isinstance(m, dict) and m.get("q")]
    if not stored:
        return None

    items: list[dict[str, Any]] = []
    for mistake in stored:
        options = mistake.get("options")
        correct = mistake.get("correct")
        if not options or correct is None:
            # Older/foreign mistake records lack the choices — recover them from content.json.
            found = _find_question(mistake.get("q", ""))
            if not found:
                continue
            options, correct = found["options"], found["correct"]
        items.append(
            {
                "q": mistake["q"],
                "options": options,
                "correct": correct,
                "module_id": mistake.get("moduleId"),
                "topic_num": mistake.get("topicNum"),
                "topic_name": mistake.get("topicName", ""),
            }
        )

    if not items:
        return None
    rng.shuffle(items)
    items = items[:MISTAKES_SESSION_SIZE]
    session = QuizSession(
        user_id=user_id, mode="mistakes", items=items, topic_name="Работа над ошибками"
    )
    SESSIONS[user_id] = session
    return session


_QUESTION_INDEX: dict[str, dict[str, Any]] = {}


def _find_question(question_text: str) -> Optional[dict[str, Any]]:
    if not _QUESTION_INDEX:
        for module_id, topics in content.MODULES_CONTENT.items():
            for topic in topics:
                for test in topic.get("tests", []):
                    if test.get("q"):
                        _QUESTION_INDEX[test["q"]] = {
                            "options": test.get("options", []),
                            "correct": test.get("correct", 0),
                            "module_id": module_id,
                            "topic_num": topic["num"],
                        }
    return _QUESTION_INDEX.get(question_text)


def answer_choice(session: QuizSession, chosen_index: int) -> tuple[bool, dict[str, Any]]:
    """Record an answer to the current multiple-choice item and advance."""
    item = session.current()
    if item is None:
        return False, {}

    is_correct = chosen_index == item.get("correct")

    if is_correct:
        # XP is earned per correct answer only — the site pushes its reward key inside the
        # `if(ok)` branch of pickTest/pickDef, so a wrong answer must never bank one.
        session.reward_keys.append(reward_key(session.mode, item.get("q", "")))
        session.correct += 1
        if session.mode == "mistakes":
            session.solved.append(item.get("q", ""))
    else:
        session.wrong.append(
            {
                "q": item.get("q", ""),
                "options": item.get("options", []),
                "correct": item.get("correct", 0),
                "moduleId": item.get("module_id"),
                "topicNum": item.get("topic_num"),
                "topicName": item.get("topic_name", ""),
            }
        )

    session.index += 1
    session.revealed = False
    return is_correct, item


def answer_flash(session: QuizSession, knew_it: bool) -> None:
    """Record a self-graded flashcard and advance."""
    item = session.current()
    if item is None:
        return
    if knew_it:
        # Same rule as the choice questions: the site only banks a flashcard's key inside
        # `advance(known)`'s `if(known)` branch, so "не знал" earns nothing.
        session.reward_keys.append(reward_key("flash", item.get("front", "")))
        session.correct += 1
    session.index += 1
    session.revealed = False
