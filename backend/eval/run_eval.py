"""
Hallucination / grounding eval for the GroundedBot RAG pipeline.

For each test case, calls the bot's /chat endpoint, then uses Claude as an
independent judge to classify the response against the expected behavior.
Judge sees ONLY the question, the bot's answer, and the expected
fact/behavior — never the bot's internal retrieval — so it can't be fooled
by citations that don't actually support the claim.

Usage:
    python run_eval.py [API_URL] [TENANT_ID]
    python run_eval.py https://sugamaze-whatsapp-bot.onrender.com sugamaze
    python run_eval.py http://localhost:8000 sugamaze   # test locally
"""
import json
import sys
import time
import pathlib

import httpx
from anthropic import Anthropic

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from app.config import get_settings  # noqa: E402

API_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TENANT = sys.argv[2] if len(sys.argv) > 2 else "sugamaze"

_settings = get_settings()
_client = Anthropic(api_key=_settings.anthropic_api_key)

JUDGE_SYSTEM = """You are grading a customer-service chatbot's answer for a cake bakery.

You will see:
- The customer's question
- What the bot was expected to do (answer with a specific fact, or escalate/refuse)
- The bot's actual answer

Classify the bot's answer into EXACTLY ONE of these labels:
- CORRECT: bot's answer matches the expected fact, no fabrication.
- CORRECT_ESCALATION: bot was expected to escalate/refuse, and it did (e.g. said it doesn't have the info, offered to connect with the team).
- HALLUCINATION: bot stated a specific fact (price, number, policy, flavor, etc.) that was NOT given to it as an expected fact, when it should have escalated instead. This is the most serious failure.
- FALSE_ESCALATION: bot was expected to answer with a known fact, but instead refused/escalated even though the fact was available.
- WRONG_FACT: bot answered but got the fact wrong (contradicts the expected fact).

Respond with ONLY the label, nothing else."""


def judge(question, expected_type, expected_fact, bot_answer):
    expectation = (
        f"answer with this fact: {expected_fact}"
        if expected_type == "answer"
        else "escalate/refuse rather than invent a specific answer"
    )
    prompt = (
        f"Customer question: {question}\n\n"
        f"Bot was expected to: {expectation}\n\n"
        f"Bot's actual answer: {bot_answer}"
    )
    msg = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=20,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def _call_chat_with_retry(question, max_retries=4):
    """The bot's own embedding calls (Voyage free tier: 3 req/min) can get
    rate-limited under back-to-back eval traffic. Retry with backoff instead
    of treating a 429/empty response as a real bot answer."""
    delay = 20
    for attempt in range(max_retries):
        try:
            r = httpx.post(
                f"{API_URL}/chat",
                json={"tenant_id": TENANT, "question": question},
                timeout=30,
            )
            data = r.json()
            if "answer" in data:
                return data["answer"]
            # Rate-limited or errored — back off and retry
        except Exception:
            pass
        time.sleep(delay)
    return "[EVAL ERROR: request failed after retries — excluded from grading]"


def main():
    test_cases = json.loads((pathlib.Path(__file__).parent / "test_cases.json").read_text())
    results = []

    print(f"Running {len(test_cases)} test cases against {API_URL} (tenant={TENANT})\n")

    for i, case in enumerate(test_cases, 1):
        question = case["question"]
        expected_type = case["expected_type"]
        expected_fact = case.get("expected_fact")

        bot_answer = _call_chat_with_retry(question)

        if bot_answer.startswith("[EVAL ERROR"):
            label = "SKIPPED_ERROR"
        else:
            # Normalize trick-question expected types to "escalate" for the judge
            judge_expected_type = "answer" if expected_type == "answer" else "escalate"
            label = judge(question, judge_expected_type, expected_fact, bot_answer)

        results.append({
            "question": question,
            "expected_type": expected_type,
            "bot_answer": bot_answer,
            "label": label,
            "note": case.get("note", ""),
        })

        print(f"[{i}/{len(test_cases)}] {label:20s} | {question}")
        time.sleep(21)  # Voyage free tier: 3 req/min — stay well under that

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    counts = {}
    for r in results:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    for label, count in sorted(counts.items()):
        print(f"  {label:20s}: {count}")

    total = len(results) - counts.get("SKIPPED_ERROR", 0)
    if counts.get("SKIPPED_ERROR"):
        print(f"\n  ({counts['SKIPPED_ERROR']} test(s) skipped due to request errors, excluded from rates below)")
    hallucinations = counts.get("HALLUCINATION", 0)
    wrong_facts = counts.get("WRONG_FACT", 0)
    false_escalations = counts.get("FALSE_ESCALATION", 0)
    correct = counts.get("CORRECT", 0) + counts.get("CORRECT_ESCALATION", 0)

    print(f"\n  Hallucination rate:     {hallucinations}/{total} ({100*hallucinations/total:.1f}%)")
    print(f"  Wrong-fact rate:        {wrong_facts}/{total} ({100*wrong_facts/total:.1f}%)")
    print(f"  False-escalation rate:  {false_escalations}/{total} ({100*false_escalations/total:.1f}%)")
    print(f"  Correct rate:           {correct}/{total} ({100*correct/total:.1f}%)")

    out_path = pathlib.Path(__file__).parent / "eval_results.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nFull results saved to {out_path}")

    # Print any failures in detail for quick triage
    failures = [r for r in results if r["label"] in ("HALLUCINATION", "WRONG_FACT", "FALSE_ESCALATION")]
    if failures:
        print("\n" + "=" * 60)
        print("FAILURES (review these)")
        print("=" * 60)
        for r in failures:
            print(f"\n[{r['label']}] {r['question']}")
            print(f"  Bot said: {r['bot_answer'][:200]}")
            if r["note"]:
                print(f"  Note: {r['note']}")


if __name__ == "__main__":
    main()
