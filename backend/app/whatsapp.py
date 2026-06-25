"""
WhatsApp Business (Meta Cloud API) glue: verify the webhook, pull the
customer's text out of an incoming payload, and send the bot's reply back.
"""
import httpx

from .config import get_settings

_settings = get_settings()
GRAPH_URL = "https://graph.facebook.com/v21.0"

# Temporary diagnostic — recent delivery-status callbacks Meta sent us (e.g.
# delivered/read/failed for messages we sent), queryable via /debug/config.
recent_statuses = []


def extract_status(payload: dict):
    """Capture delivery-status callbacks (sent/delivered/read/failed) for
    diagnostics. These arrive separately from inbound customer messages."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        statuses = change.get("statuses")
        if statuses:
            recent_statuses.append(statuses[0])
            del recent_statuses[:-10]  # keep last 10 only
    except (KeyError, IndexError, TypeError):
        pass


def verify(mode: str, token: str, challenge: str):
    if mode == "subscribe" and token == _settings.whatsapp_verify_token:
        return challenge
    return None


def extract_message(payload: dict):
    """Return (from_number, text) for the first text message in the webhook
    payload, or None if there isn't one (e.g. delivery-status callbacks)."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            return None
        return msg["from"], msg["text"]["body"]
    except (KeyError, IndexError, TypeError):
        return None


def extract_button_reply(payload: dict):
    """Return (from_number, button_id) if the inbound message is a button
    click from an interactive message, else None."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "interactive":
            return None
        interactive = msg["interactive"]
        if interactive.get("type") != "button_reply":
            return None
        return msg["from"], interactive["button_reply"]["id"]
    except (KeyError, IndexError, TypeError):
        return None


def send_message(to: str, text: str):
    url = f"{GRAPH_URL}/{_settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {_settings.whatsapp_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def send_template(to: str, template_name: str, params: list[str], language="en_US"):
    """Send an approved message template — required for business-initiated
    messages to a recipient outside the 24-hour customer-service window
    (e.g. escalation alerts to a shop owner who hasn't recently messaged
    the bot). Free-form text (send_message) gets rejected with error 131047
    in that case; templates bypass that restriction entirely."""
    url = f"{GRAPH_URL}/{_settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {_settings.whatsapp_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params],
                }
            ],
        },
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def send_buttons(to: str, body_text: str, buttons: list[tuple[str, str]]):
    """buttons is a list of (id, title) pairs, max 3 per WhatsApp's limit."""
    url = f"{GRAPH_URL}/{_settings.whatsapp_phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {_settings.whatsapp_token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title}}
                    for bid, title in buttons
                ]
            },
        },
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()
