"""
Lightweight, persistent usage tracking so the shop owner can see roughly
what the bot is costing without needing to check Anthropic/Voyage's own
billing consoles. Counts are approximate estimates, not an invoice — always
defer to the actual provider dashboards for exact billing.

Persisted on the same disk as the vector store / admin settings, keyed by
calendar month, so figures reset naturally each month and survive restarts.
"""
import json
import pathlib
from datetime import datetime, timezone

from . import admin_settings

USAGE_FILE = admin_settings.ADMIN_DATA_DIR / "usage.json"

# Rough, approximate per-token pricing (USD) — update if Anthropic/Voyage
# pricing changes. These produce an ESTIMATE for the admin dashboard, not an
# exact bill; the provider's own console is the source of truth for billing.
CLAUDE_INPUT_COST_PER_MTOK = 3.0
CLAUDE_OUTPUT_COST_PER_MTOK = 15.0
VOYAGE_COST_PER_MTOK = 0.02

RENDER_FIXED_MONTHLY_USD = 7.25  # Starter instance + 1GB persistent disk


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ensure_dir():
    admin_settings.ADMIN_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load() -> dict:
    _ensure_dir()
    if USAGE_FILE.exists():
        try:
            return json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(data: dict):
    _ensure_dir()
    USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _empty_month() -> dict:
    return {
        "claude_calls": 0,
        "claude_input_tokens": 0,
        "claude_output_tokens": 0,
        "voyage_calls": 0,
    }


def record_claude_call(input_tokens: int, output_tokens: int):
    data = _load()
    month = _month_key()
    m = data.setdefault(month, _empty_month())
    m["claude_calls"] += 1
    m["claude_input_tokens"] += input_tokens
    m["claude_output_tokens"] += output_tokens
    _save(data)


def record_voyage_call(n: int = 1):
    data = _load()
    month = _month_key()
    m = data.setdefault(month, _empty_month())
    m["voyage_calls"] += n
    _save(data)


def get_current_month_usage() -> dict:
    data = _load()
    month = _month_key()
    m = data.get(month, _empty_month())

    claude_cost = (
        m["claude_input_tokens"] / 1_000_000 * CLAUDE_INPUT_COST_PER_MTOK
        + m["claude_output_tokens"] / 1_000_000 * CLAUDE_OUTPUT_COST_PER_MTOK
    )
    # Voyage cost is tiny and we don't track exact token counts per call
    # (the embedding function is internal to chromadb) — approximate using
    # a small average tokens-per-call assumption for a rough estimate only.
    approx_voyage_tokens = m["voyage_calls"] * 50
    voyage_cost = approx_voyage_tokens / 1_000_000 * VOYAGE_COST_PER_MTOK

    return {
        "month": month,
        "claude_calls": m["claude_calls"],
        "claude_input_tokens": m["claude_input_tokens"],
        "claude_output_tokens": m["claude_output_tokens"],
        "estimated_claude_cost_usd": round(claude_cost, 2),
        "voyage_calls": m["voyage_calls"],
        "estimated_voyage_cost_usd": round(voyage_cost, 2),
        "render_fixed_cost_usd": RENDER_FIXED_MONTHLY_USD,
        "estimated_total_cost_usd": round(claude_cost + voyage_cost + RENDER_FIXED_MONTHLY_USD, 2),
        "note": "Estimates only, based on approximate per-token pricing. Check console.anthropic.com and voyageai.com for exact billing.",
    }
