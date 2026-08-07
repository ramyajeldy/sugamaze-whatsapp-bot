"""
WhatsApp Business (Meta Cloud API) glue: verify the webhook, pull the
customer's text out of an incoming payload, and send the bot's reply back.

One Meta App/webhook serves every tenant's phone number. Send/forward calls
take explicit WhatsAppCreds (token + phone_number_id) for the tenant that
owns the conversation, rather than reading a single global setting — that's
what lets one process serve many tenants' WhatsApp numbers at once.
"""
from dataclasses import dataclass

import httpx

from .config import get_settings

_settings = get_settings()
GRAPH_URL = "https://graph.facebook.com/v21.0"

# Temporary diagnostic — recent delivery-status callbacks Meta sent us (e.g.
# delivered/read/failed for messages we sent), queryable via /debug/config.
recent_statuses = []


@dataclass(frozen=True)
class WhatsAppCreds:
    token: str
    phone_number_id: str


def creds_for(tenant) -> WhatsAppCreds:
    """Build WhatsAppCreds from a tenants.TenantConfig."""
    return WhatsAppCreds(token=tenant.whatsapp_token, phone_number_id=tenant.whatsapp_phone_number_id)


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


def extract_phone_number_id(payload: dict):
    """Return the Meta phone_number_id the inbound webhook was sent to (i.e.
    which tenant's WhatsApp number received it), or None if absent."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        return change["metadata"]["phone_number_id"]
    except (KeyError, IndexError, TypeError):
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


def extract_media(payload: dict):
    """Return (from_number, media_type, media_id, caption) for an inbound
    image/document message (e.g. a customer's cake design idea), or None.
    Caption may be empty string."""
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return None
        msg = messages[0]
        media_type = msg.get("type")
        if media_type not in {"image", "document"}:
            return None
        media = msg[media_type]
        return msg["from"], media_type, media["id"], media.get("caption", "")
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


def send_message(creds: WhatsAppCreds, to: str, text: str):
    url = f"{GRAPH_URL}/{creds.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {creds.token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=20)
    try:
        r.raise_for_status()
    except httpx.HTTPStatusError:
        # Graph API error bodies (e.g. "recipient not in allowed list",
        # invalid token, wrong phone number ID) are in the response body,
        # not the generic status message — log it so failures are diagnosable.
        print(f"[WHATSAPP SEND ERROR] {r.status_code}: {r.text}")
        raise
    return r.json()


def forward_media(creds: WhatsAppCreds, to: str, media_type: str, media_id: str, caption: str = ""):
    """Re-send a media item the bot received (by its Meta media id) to a
    different recipient — used to forward a customer's design photo/file
    straight to the shop's WhatsApp. Works because the media stays hosted
    on the same WhatsApp Business Account; no download/re-upload needed."""
    url = f"{GRAPH_URL}/{creds.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {creds.token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": media_type,
        media_type: {"id": media_id, "caption": caption},
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def send_template(creds: WhatsAppCreds, to: str, template_name: str, params: list[str], language="en_US"):
    """Send an approved message template — required for business-initiated
    messages to a recipient outside the 24-hour customer-service window
    (e.g. escalation alerts to a shop owner who hasn't recently messaged
    the bot). Free-form text (send_message) gets rejected with error 131047
    in that case; templates bypass that restriction entirely."""
    url = f"{GRAPH_URL}/{creds.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {creds.token}"}
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


def send_list(creds: WhatsAppCreds, to: str, header_text: str, body_text: str, button_text: str,
              rows: list[tuple[str, str]]):
    """A WhatsApp 'list' interactive message — unlike buttons (max 3), lists
    support up to 10 rows. rows is a list of (id, title) pairs."""
    url = f"{GRAPH_URL}/{creds.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {creds.token}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header_text},
            "body": {"text": body_text},
            "action": {
                "button": button_text,
                "sections": [
                    {
                        "rows": [
                            {"id": rid, "title": title} for rid, title in rows
                        ]
                    }
                ],
            },
        },
    }
    r = httpx.post(url, json=payload, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def extract_list_reply(payload: dict):
    """Return (from_number, row_id) if the inbound message is a row
    selection from a list message, else None."""
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
        if interactive.get("type") != "list_reply":
            return None
        return msg["from"], interactive["list_reply"]["id"]
    except (KeyError, IndexError, TypeError):
        return None


def send_buttons(creds: WhatsAppCreds, to: str, body_text: str, buttons: list[tuple[str, str]]):
    """buttons is a list of (id, title) pairs, max 3 per WhatsApp's limit."""
    url = f"{GRAPH_URL}/{creds.phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {creds.token}"}
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
