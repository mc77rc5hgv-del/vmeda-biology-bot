# -*- coding: utf-8 -*-
"""Тесты для scripts/ai_benchmark.py — только детерминированные части, не требующие сети/ключей
(format_question_text, sample_questions, summarize, format_report/format_comparison). run_one()/
main() делают реальные вызовы к AI-провайдерам и стоят реальных денег — намеренно НЕ покрыты
автоматическими тестами, см. докстринг самого скрипта ("DELIBERATELY NOT part of the bot...")."""
import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

_spec = importlib.util.spec_from_file_location("ai_benchmark", os.path.join(REPO_ROOT, "scripts", "ai_benchmark.py"))
ai_benchmark = importlib.util.module_from_spec(_spec)
_prev_cwd = os.getcwd()
os.chdir(REPO_ROOT)  # repositories.knowledge (импортируется внутри ai_benchmark.py) читает JSON
# относительными путями — тот же манёвр, что и в tests/_bootstrap.py для telegram_bot
try:
    _spec.loader.exec_module(ai_benchmark)
finally:
    os.chdir(_prev_cwd)


def main():
    # ---- 1. format_question_text: question + lettered options, one per line ----
    q = {"question": "Тестовый вопрос?", "options": {"а": "Вариант А", "б": "Вариант Б"}, "correct": "а"}
    text = ai_benchmark.format_question_text(q)
    assert text == "Тестовый вопрос?\nа) Вариант А\nб) Вариант Б"
    print("1. format_question_text: OK")

    # ---- 2. sample_questions: against the REAL bank (1040 questions, 10 parts) — part filter and
    # reproducible seeded sampling (needed for --compare-with to mean anything across runs) ----
    all_q = ai_benchmark.sample_questions(ai_benchmark.knowledge.ANATOMY_EXAM_TEST_PARTS)
    assert len(all_q) == 1040
    part1 = ai_benchmark.sample_questions(ai_benchmark.knowledge.ANATOMY_EXAM_TEST_PARTS, part_filter=1)
    assert len(part1) == 102 and all(p[0] == 1 for p in part1)
    sampled = ai_benchmark.sample_questions(ai_benchmark.knowledge.ANATOMY_EXAM_TEST_PARTS, sample_size=25, seed=42)
    assert len(sampled) == 25
    sampled_again = ai_benchmark.sample_questions(ai_benchmark.knowledge.ANATOMY_EXAM_TEST_PARTS, sample_size=25, seed=42)
    assert sampled == sampled_again, "same seed must give the same sample, or --compare-with runs aren't comparable"
    sample_size_over_pool = ai_benchmark.sample_questions(ai_benchmark.knowledge.ANATOMY_EXAM_TEST_PARTS, part_filter=1, sample_size=9999)
    assert len(sample_size_over_pool) == 102, "sample_size larger than the pool must return the whole pool, not crash"
    print("2. sample_questions: real bank size, part filter, reproducible seeded sampling: OK")

    # ---- 3. summarize: accuracy / by-part / by-confidence-action aggregation, errored entries
    # excluded from grading but counted separately ----
    fake_results = [
        {"part_id": 1, "raw_correct": True, "confidence_action": "serve", "input_tokens": 10, "output_tokens": 5, "error": None},
        {"part_id": 1, "raw_correct": False, "confidence_action": "escalate", "input_tokens": 20, "output_tokens": 8, "error": None},
        {"part_id": 2, "raw_correct": True, "confidence_action": "serve", "input_tokens": 15, "output_tokens": 6, "error": None},
        {"part_id": 2, "raw_correct": False, "confidence_action": "serve", "input_tokens": 12, "output_tokens": 4, "error": None},
        {"error": "simulated network failure"},
    ]
    summary = ai_benchmark.summarize(fake_results)
    assert summary["total"] == 5
    assert summary["errored"] == 1
    assert summary["graded"] == 4
    assert summary["correct"] == 2
    assert abs(summary["accuracy"] - 0.5) < 1e-9
    assert summary["by_part"][1] == {"total": 2, "correct": 1}
    assert summary["by_part"][2] == {"total": 2, "correct": 1}
    assert summary["by_confidence_action"]["serve"] == {"total": 3, "correct": 2}
    assert summary["by_confidence_action"]["escalate"] == {"total": 1, "correct": 0}
    assert summary["wrong_answers_total"] == 2
    assert summary["wrong_answers_flagged_escalate"] == 1, "only the ESCALATE-flagged wrong answer counts here"
    assert abs(summary["verifier_flagging_rate"] - 0.5) < 1e-9
    assert summary["total_input_tokens"] == 57
    assert summary["total_output_tokens"] == 23
    print("3. summarize: accuracy/by-part/by-action aggregation, verifier flagging rate, errors excluded from grading: OK")

    # ---- 3b. summarize: all-errored input degrades to accuracy=None instead of dividing by zero ----
    empty_summary = ai_benchmark.summarize([{"error": "boom"}])
    assert empty_summary["graded"] == 0
    assert empty_summary["accuracy"] is None
    assert empty_summary["verifier_flagging_rate"] is None
    print("3b. summarize: all-errored input degrades gracefully, no division by zero: OK")

    # ---- 4. format_report/format_comparison: render without crashing, carry the key numbers ----
    report = ai_benchmark.format_report(summary)
    assert "50.0%" in report
    assert "часть 1" in report and "часть 2" in report
    comparison_text = ai_benchmark.format_comparison(summary, summary)
    assert "+0.0%" in comparison_text, "comparing a summary with itself must show a zero delta"
    print("4. format_report/format_comparison render without crashing, contain the key numbers: OK")

    # ---- 5. estimate_result_cost_usd: deterministic token->USD conversion for the --max-cost-usd
    # safety cap (uses OpenAI's own price constants, not a made-up number) ----
    price_in = ai_benchmark.ai_openai_provider.PRICE_INPUT_PER_1M
    price_out = ai_benchmark.ai_openai_provider.PRICE_OUTPUT_PER_1M
    cost = ai_benchmark.estimate_result_cost_usd({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert abs(cost - (price_in + price_out)) < 1e-9
    assert ai_benchmark.estimate_result_cost_usd({}) == 0.0, "missing token fields must not crash, cost 0"
    print("5. estimate_result_cost_usd: converts tokens to USD via OpenAI's own price constants: OK")

    # ---- 6. main(): --all without --confirm-cost must abort via sys.exit(1) BEFORE touching any
    # provider — this is the actual safety property (a copy-pasted --all command can't silently
    # burn through the whole 1040-question bank), not just an argparse detail ----
    import asyncio
    import contextlib
    import io
    orig_argv = sys.argv
    sys.argv = ["ai_benchmark.py", "--all"]
    captured_err = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured_err):
            try:
                asyncio.run(ai_benchmark.main())
                exited, exit_code = False, None
            except SystemExit as exc:
                exited, exit_code = True, exc.code
    finally:
        sys.argv = orig_argv
    assert exited and exit_code == 1, "a run above CONFIRM_COST_QUESTION_THRESHOLD without --confirm-cost must sys.exit(1)"
    assert "--confirm-cost" in captured_err.getvalue()
    print("6. main(): --all without --confirm-cost aborts before any provider call: OK")

    print("\nAll ai_benchmark tests passed!")


if __name__ == "__main__":
    main()
