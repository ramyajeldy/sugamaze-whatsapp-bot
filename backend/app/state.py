"""
In-memory per-customer conversation state: tracks the last time each phone
number messaged the bot, so a background task can nudge idle customers with
a "still there?" check-in. Process-local (fine for a single-instance
deployment); would need a shared store (Redis, etc.) for multi-instance.
"""
import time

_last_message_at: dict[str, float] = {}
_followup_sent: set[str] = set()
_conversation_ended: set[str] = set()

# When the server starts, Meta may replay webhooks from the previous session
# (messages that arrived while the server was down). These arrive within the
# first few seconds of startup and would incorrectly re-add customers who
# already finished chatting to idle tracking. We ignore any touches that
# arrive within this window for idle-check-in purposes.
_server_start: float = time.time()
_STARTUP_GRACE_SECONDS = 60


def touch(phone: str):
    """Call whenever a customer sends any message — resets their idle timer
    and reopens the session (clears any previous conversation-ended flag)."""
    _last_message_at[phone] = time.time()
    _followup_sent.discard(phone)
    _conversation_ended.discard(phone)


def idle_customers(idle_seconds: float):
    """Phones eligible for an idle check-in: quiet for >= idle_seconds,
    not already nudged, not in a conversation that was explicitly ended,
    and whose last message arrived after the startup replay grace window."""
    now = time.time()
    replay_cutoff = _server_start + _STARTUP_GRACE_SECONDS
    return [
        phone for phone, last in _last_message_at.items()
        if now - last >= idle_seconds
        and last >= replay_cutoff
        and phone not in _followup_sent
        and phone not in _conversation_ended
    ]


def mark_followup_sent(phone: str):
    _followup_sent.add(phone)


def end_conversation(phone: str):
    """Call when the customer explicitly ends the chat (taps 'No' on the
    idle check-in). Prevents any further nudges unless they send a new
    message themselves, which clears the ended flag via touch()."""
    _last_message_at.pop(phone, None)
    _followup_sent.discard(phone)
    _conversation_ended.add(phone)
