"""
In-memory per-customer conversation state: tracks the last time each phone
number messaged the bot, so a background task can nudge idle customers with
a "still there?" check-in. Process-local (fine for a single-instance
deployment); would need a shared store (Redis, etc.) for multi-instance.
"""
import time

_last_message_at: dict[str, float] = {}
_followup_sent: set[str] = set()


def touch(phone: str):
    """Call whenever a customer sends any message — resets their idle timer."""
    _last_message_at[phone] = time.time()
    _followup_sent.discard(phone)


def idle_customers(idle_seconds: float):
    """Phones that have been quiet for >= idle_seconds and haven't been
    nudged yet since their last message."""
    now = time.time()
    return [
        phone for phone, last in _last_message_at.items()
        if now - last >= idle_seconds and phone not in _followup_sent
    ]


def mark_followup_sent(phone: str):
    _followup_sent.add(phone)
