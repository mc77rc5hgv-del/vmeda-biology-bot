#!/usr/bin/env python3
"""AI-конвейер: бенчмарк реальной точности на эталонной базе вопросов.

Прогоняет РЕАЛЬНЫЙ конвейер (ai.vision_parser -> ai.router.route_bucket -> ai.rag.search_for_task
-> ai.service.solve(quick=True) -> ai.validator/ai.mcq_verifier -> ai.confidence.decide) по выборке
из 1040-вопросного официального теста кафедры нормальной анатомии ВМедА (anatomy_exam_test.json —
см. ai/reference_bank.py) и сверяет краткий ответ модели с ОБЪЕКТИВНО известным правильным
вариантом. Это единственный контент в боте с проверяемым "правильно/неправильно" без ещё одного
обращения к модели-судье — см. CLAUDE.md/ai/reference_bank.py, почему Биология/Физика/Химия сюда
не входят.

Отвечает на вопрос "стало ли ЛУЧШЕ после архитектурных изменений, а не просто дороже" — сохраняй
JSON-результаты (--output) между прогонами и сравнивай (--compare-with), а не полагайся на
субъективное "вроде ответы стали приличнее".

ВАЖНО про метрику "verifier_flagging_rate" в отчёте: бенчмарк тестирует конвейер ПРОТИВ ТОГО ЖЕ
банка, из которого ai.mcq_verifier берёт эталонные ответы — поэтому она НЕ измеряет, ловит ли
verifier реальные ошибки на произвольных вопросах (для этого нужен held-out набор), а проверяет
только САМОСОГЛАСОВАННОСТЬ: если модель ответила неправильно на вопрос ИЗ банка, confidence-роутер
обязан был это заметить (ESCALATE) почти всегда — значение заметно ниже 100% значит баг в
сопоставлении/извлечении буквы ответа, а не "verifier неидеален на новых вопросах".

DELIBERATELY NOT part of the bot (telegram_bot.py / requirements.txt) or the deployed bot process
on Railway — тратит реальные токены реальных провайдеров. Запускать вручную, с реальными ключами:

    export OPENAI_API_KEY=...
    python3 scripts/ai_benchmark.py --sample 50
    python3 scripts/ai_benchmark.py --all --concurrency 8 --output results_before.json
    python3 scripts/ai_benchmark.py --all --compare-with results_before.json

Опции:
    --sample N        сколько вопросов взять случайной выборкой (по умолчанию 50)
    --all              прогнать все 1040 вопросов вместо выборки
    --part N           ограничиться одной частью теста (1-10, см. anatomy_exam_test.json)
    --seed N           seed для воспроизводимой выборки
    --concurrency N    сколько вопросов гонять параллельно (по умолчанию 5 — не долбить API)
    --output PATH      куда сохранить полный JSON с результатами
    --compare-with PATH  путь к JSON предыдущего запуска — показать разницу в точности
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ai/* модули не тянут aiogram/BOT_TOKEN/контент бота (см. CLAUDE.md — тот же принцип, что
# позволяет ai/rag.py и остальным жить без циклического импорта telegram_bot) -- можно
# импортировать напрямую, без запуска самого бота.
from ai import confidence as ai_confidence  # noqa: E402
from ai import mcq_verifier as ai_mcq_verifier  # noqa: E402
from ai import rag as ai_rag  # noqa: E402
from ai import reference_bank as ai_reference_bank  # noqa: E402
from ai import router as ai_router  # noqa: E402
from ai import service as ai_service  # noqa: E402
from ai import validator as ai_validator  # noqa: E402
from ai import vision_parser as ai_vision_parser  # noqa: E402

# repositories.knowledge читает JSON-файлы контента относительными путями (см. CLAUDE.md) —
# импортировать нужно с корнем репозитория в качестве текущей рабочей директории.
_prev_cwd = os.getcwd()
os.chdir(REPO_ROOT)
try:
    from repositories import knowledge  # noqa: E402
finally:
    os.chdir(_prev_cwd)


def format_question_text(q: dict) -> str:
    """Вопрос + варианты в виде текста — так же, как выглядел бы сфотографированный тестовый
    билет, если бы студент прислал его текстом вместо фото."""
    lines = [q["question"]]
    for letter, text in q["options"].items():
        lines.append(f"{letter}) {text}")
    return "\n".join(lines)


def sample_questions(parts: list, *, part_filter: int = None, sample_size: int = None, seed: int = None) -> list:
    """Возвращает [(part_id, part_title, question_dict), ...] — весь банк, отфильтрованный по
    part_filter, если задан, и урезанный до sample_size случайных записей (детерминированно при
    заданном seed), если sample_size меньше размера пула."""
    pool = []
    for part in parts:
        if part_filter is not None and part["id"] != part_filter:
            continue
        for q in part["questions"]:
            pool.append((part["id"], part["title"], q))
    if sample_size is not None and sample_size < len(pool):
        pool = random.Random(seed).sample(pool, sample_size)
    return pool


async def run_one(part_id: int, part_title: str, q: dict) -> dict:
    """Прогоняет ОДИН вопрос через реальный конвейер конца в конец и возвращает плоский dict —
    удобно и для печати построчного прогресса, и для сериализации в итоговый JSON."""
    question_text = format_question_text(q)
    started = time.monotonic()
    result = {
        "part_id": part_id, "part_title": part_title, "question": q["question"],
        "correct_option": q["correct"],
    }
    try:
        task, parse_usage = await ai_vision_parser.parse_task(text=question_text)
        bucket = ai_router.route_bucket(task)
        snippets, rag_usage = await ai_rag.search_for_task(task)
        rag_context = ai_rag.format_context(snippets)
        answer, _, usage, _attempts_log = await ai_service.solve(
            task=task, quick=True, bucket=bucket, rag_context=rag_context,
        )
        validation = ai_validator.validate_answer(task, answer)
        mcq_verification = ai_mcq_verifier.verify_mcq(task, answer)
        decision = ai_confidence.decide(
            task, validation, rag_grounded=bool(rag_context), mcq_verification=mcq_verification,
        )
        chosen = ai_mcq_verifier.extract_chosen_letter(answer, q["options"])
        result.update({
            "answer": answer,
            "chosen_option": chosen,
            "raw_correct": chosen == q["correct"],
            "task_type": task.type,
            "task_confidence": task.confidence,
            "bucket": bucket,
            "confidence_action": decision.action,
            "confidence_score": decision.score,
            "mcq_verification_checked": mcq_verification.checked,
            "mcq_verification_matched": mcq_verification.matched,
            "input_tokens": parse_usage.get("input_tokens", 0) + rag_usage.get("input_tokens", 0)
            + usage.get("input_tokens", 0),
            "output_tokens": parse_usage.get("output_tokens", 0) + usage.get("output_tokens", 0),
            "elapsed_sec": round(time.monotonic() - started, 2),
            "error": None,
        })
    except Exception as exc:
        result.update({
            "answer": None, "chosen_option": None, "raw_correct": False,
            "elapsed_sec": round(time.monotonic() - started, 2), "error": repr(exc),
        })
    return result


def summarize(results: list) -> dict:
    """Агрегирует сырые результаты run_one в отчёт: общая точность, точность по частям теста и по
    confidence_action, а также verifier_flagging_rate (см. предупреждение в докстринге модуля)."""
    graded = [r for r in results if not r.get("error")]
    correct = [r for r in graded if r["raw_correct"]]
    by_part = defaultdict(lambda: {"total": 0, "correct": 0})
    by_action = defaultdict(lambda: {"total": 0, "correct": 0})
    total_input_tokens = 0
    total_output_tokens = 0
    wrong_flagged_escalate = 0
    wrong_total = 0
    for r in graded:
        by_part[r["part_id"]]["total"] += 1
        by_part[r["part_id"]]["correct"] += int(r["raw_correct"])
        by_action[r["confidence_action"]]["total"] += 1
        by_action[r["confidence_action"]]["correct"] += int(r["raw_correct"])
        total_input_tokens += r.get("input_tokens", 0)
        total_output_tokens += r.get("output_tokens", 0)
        if not r["raw_correct"]:
            wrong_total += 1
            if r["confidence_action"] == ai_confidence.ESCALATE:
                wrong_flagged_escalate += 1
    return {
        "total": len(results),
        "errored": len(results) - len(graded),
        "graded": len(graded),
        "correct": len(correct),
        "accuracy": (len(correct) / len(graded)) if graded else None,
        "by_part": {k: v for k, v in sorted(by_part.items())},
        "by_confidence_action": dict(by_action),
        "wrong_answers_total": wrong_total,
        "wrong_answers_flagged_escalate": wrong_flagged_escalate,
        "verifier_flagging_rate": (wrong_flagged_escalate / wrong_total) if wrong_total else None,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
    }


def format_report(summary: dict) -> str:
    lines = [
        "=" * 70,
        "AI BENCHMARK — реальная точность на эталонной базе (anatomy_exam_test.json)",
        "=" * 70,
        f"Всего вопросов: {summary['total']}  (оценено: {summary['graded']}, ошибок конвейера: {summary['errored']})",
    ]
    if summary["accuracy"] is not None:
        lines.append(f"Точность (raw quick-answer): {summary['accuracy']:.1%} ({summary['correct']}/{summary['graded']})")
    lines.append("")
    lines.append("По частям теста:")
    for part_id, stats in summary["by_part"].items():
        acc = stats["correct"] / stats["total"] if stats["total"] else 0.0
        lines.append(f"  часть {part_id}: {acc:.1%} ({stats['correct']}/{stats['total']})")
    lines.append("")
    lines.append("По confidence_action (SERVE/VERIFY/ESCALATE):")
    for action, stats in summary["by_confidence_action"].items():
        acc = stats["correct"] / stats["total"] if stats["total"] else 0.0
        lines.append(f"  {action}: {acc:.1%} правильных ({stats['correct']}/{stats['total']})")
    if summary["verifier_flagging_rate"] is not None:
        lines.append("")
        lines.append(
            f"Самосогласованность verifier'а: из {summary['wrong_answers_total']} неправильных ответов "
            f"{summary['wrong_answers_flagged_escalate']} были помечены ESCALATE "
            f"({summary['verifier_flagging_rate']:.1%}) — см. предупреждение в докстринге скрипта, "
            "это НЕ точность на новых вопросах, а проверка, что сопоставление с банком работает верно."
        )
    lines.append("")
    lines.append(f"Токены: {summary['total_input_tokens']:,} вход / {summary['total_output_tokens']:,} выход".replace(",", " "))
    return "\n".join(lines)


def format_comparison(old_summary: dict, new_summary: dict) -> str:
    lines = ["", "=" * 70, "СРАВНЕНИЕ С ПРЕДЫДУЩИМ ЗАПУСКОМ", "=" * 70]
    old_acc, new_acc = old_summary.get("accuracy"), new_summary.get("accuracy")
    if old_acc is not None and new_acc is not None:
        delta = new_acc - old_acc
        sign = "+" if delta >= 0 else ""
        lines.append(f"Точность: {old_acc:.1%} -> {new_acc:.1%}  ({sign}{delta:.1%})")
    old_tokens = old_summary.get("total_input_tokens", 0) + old_summary.get("total_output_tokens", 0)
    new_tokens = new_summary.get("total_input_tokens", 0) + new_summary.get("total_output_tokens", 0)
    lines.append(f"Токенов всего: {old_tokens:,} -> {new_tokens:,}".replace(",", " "))
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample", type=int, default=50, help="сколько вопросов взять случайной выборкой (по умолчанию 50)")
    parser.add_argument("--all", action="store_true", help="прогнать все 1040 вопросов вместо выборки")
    parser.add_argument("--part", type=int, default=None, help="ограничиться одной частью теста (1-10)")
    parser.add_argument("--seed", type=int, default=None, help="seed для воспроизводимой выборки")
    parser.add_argument("--concurrency", type=int, default=5, help="сколько вопросов гонять параллельно (по умолчанию 5)")
    parser.add_argument("--output", type=str, default=None, help="куда сохранить JSON с результатами")
    parser.add_argument("--compare-with", type=str, default=None, help="JSON предыдущего запуска — показать разницу")
    args = parser.parse_args()

    if not (os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("XAI_API_KEY")):
        print(
            "ВНИМАНИЕ: не задан ни один API-ключ (OPENAI_API_KEY/GEMINI_API_KEY/XAI_API_KEY) — "
            "все вопросы деградируют в пустой ответ (см. ai.vision_parser). Задайте хотя бы OPENAI_API_KEY.",
            file=sys.stderr,
        )

    ai_rag.configure(
        questions=knowledge.QUESTIONS, physics_questions=knowledge.PHYSICS_QUESTIONS,
        chemistry_theory=knowledge.CHEMISTRY_THEORY,
        chemistry_theory_tickets=knowledge.CHEMISTRY_THEORY_TICKETS,
        chemistry_practice_tickets=knowledge.CHEMISTRY_PRACTICE_TICKETS, anatomy=knowledge.ANATOMY,
    )
    ai_reference_bank.configure(knowledge.ANATOMY_EXAM_TEST_PARTS)

    sample_size = None if args.all else args.sample
    pool = sample_questions(knowledge.ANATOMY_EXAM_TEST_PARTS, part_filter=args.part, sample_size=sample_size, seed=args.seed)
    if not pool:
        print("Пустая выборка (проверь --part) — нечего запускать.", file=sys.stderr)
        return
    print(f"Прогоняю {len(pool)} вопрос(ов), параллельно по {args.concurrency}...", file=sys.stderr)

    semaphore = asyncio.Semaphore(args.concurrency)
    total = len(pool)
    done_count = 0

    async def run_bounded(part_id, part_title, q):
        nonlocal done_count
        async with semaphore:
            result = await run_one(part_id, part_title, q)
            done_count += 1
            status = "ERR" if result.get("error") else ("OK" if result["raw_correct"] else "WRONG")
            print(f"[{done_count}/{total}] часть {part_id} — {status}", file=sys.stderr)
            return result

    results = await asyncio.gather(*(run_bounded(part_id, part_title, q) for part_id, part_title, q in pool))

    summary = summarize(results)
    print("\n" + format_report(summary))

    out_path = Path(args.output) if args.output else Path(__file__).with_name(
        f"ai_benchmark_results_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    out_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nПолные результаты сохранены в {out_path}", file=sys.stderr)

    if args.compare_with:
        old_data = json.loads(Path(args.compare_with).read_text(encoding="utf-8"))
        print(format_comparison(old_data["summary"], summary))


if __name__ == "__main__":
    asyncio.run(main())
