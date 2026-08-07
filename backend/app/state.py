"""
In-memory per-customer conversation state: tracks the last time each phone
number messaged the bot, so a background task can nudge idle customers with
a "still there?" check-in. Process-local (fine for a single-instance
deployment); would need a shared store (Redis, etc.) for multi-instance.

Keyed by (tenant_id, phone) rather than phone alone — the same person can
message two different tenants' bots, and their idle timer and conversation
history must stay separate.
"""
import time

Key = tuple[str, str]

_last_message_at: dict[Key, float] = {}
_followup_sent: set[Key] = set()
_conversation_ended: set[Key] = set()

# Short per-customer conversation history so the bot can resolve follow-up
# questions ("how much is that one?") without re-explaining themselves.
# Capped small on purpose — this is for reference resolution, not a full
# transcript, and it's cleared whenever a conversation genuinely restarts
# (a fresh greeting, or an idle "No").
_history: dict[Key, list[dict]] = {}
MAX_HISTORY_TURNS = 6  # ~3 back-and-forth exchanges

# When the server starts, Meta may replay webhooks from the previous session
# (messages that arrived while the server was down). These arrive within the
# first few seconds of startup and would incorrectly re-add customers who
# already finished chatting to idle tracking. We ignore any touches that
# arrive within this window for idle-check-in purposes.
_server_start: float = time.time()
_STARTUP_GRACE_SECONDS = 60


def touch(tenant_id: str, phone: str):
    """Call whenever a customer sends any message — resets their idle timer
    and reopens the session (clears any previous conversation-ended flag)."""
    key = (tenant_id, phone)
    _last_message_at[key] = time.time()
    _followup_sent.discard(key)
    _conversation_ended.discard(key)


def idle_customers(idle_seconds: float) -> list[Key]:
    """(tenant_id, phone) pairs eligible for an idle check-in: quiet for >=
    idle_seconds, not already nudged, not in a conversation that was
    explicitly ended, and whose last message arrived after the startup
    replay grace window."""
    now = time.time()
    replay_cutoff = _server_start + _STARTUP_GRACE_SECONDS
    return [
        key for key, last in _last_message_at.items()
        if now - last >= idle_seconds
        and last >= replay_cutoff
        and key not in _followup_sent
        and key not in _conversation_ended
    ]


def mark_followup_sent(tenant_id: str, phone: str):
    _followup_sent.add((tenant_id, phone))


def end_conversation(tenant_id: str, phone: str):
    """Call when the customer explicitly ends the chat (taps 'No' on the
    idle check-in). Prevents any further nudges unless they send a new
    message themselves, which clears the ended flag via touch()."""
    key = (tenant_id, phone)
    _last_message_at.pop(key, None)
    _followup_sent.discard(key)
    _conversation_ended.add(key)
    clear_history(tenant_id, phone)


def get_history(tenant_id: str, phone: str) -> list[dict]:
    """Return recent turns as [{"role": "user"|"assistant", "content": str}, ...]."""
    return list(_history.get((tenant_id, phone), []))


def append_turn(tenant_id: str, phone: str, role: str, content: str):
    hist = _history.setdefault((tenant_id, phone), [])
    hist.append({"role": role, "content": content})
    del hist[:-MAX_HISTORY_TURNS]


def clear_history(tenant_id: str, phone: str):
    """Call when a conversation genuinely restarts (fresh greeting, or the
    customer ending the previous chat) so old context doesn't bleed in."""
    _history.pop((tenant_id, phone), None)
