"""
Send notifications to a tenant's team when the bot escalates (can't answer a
question) or captures a high-priority lead. Supports email and WhatsApp.

Every function takes the TenantConfig for the conversation, so alerts always
reach the right business's inbox/number — no global "the shop" any more.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from .config import get_settings
from . import whatsapp

_settings = get_settings()

# Temporary in-memory diagnostic — last error from a notification attempt,
# queryable via /debug/config since we can't view platform logs directly.
last_error = None
last_attempt = None


def notify_escalation(tenant, customer_phone: str, question: str):
    """Alert the tenant's team that a customer asked something the bot
    couldn't answer."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ESCALATION][{tenant.tenant_id}] Customer {customer_phone} asked: {question}")

    if _settings.smtp_user and _settings.smtp_password:
        _send_email(tenant, customer_phone, question, timestamp)
    else:
        print("[ESCALATION] Email disabled (no SMTP_USER or SMTP_PASSWORD)")

    _send_whatsapp(tenant, customer_phone, question, timestamp)


def notify_priority_lead(tenant, customer_phone: str, label: str):
    """Alert the tenant that a customer took a high-intent action (placing a
    custom order, requesting an assessment booking, etc.). Distinct from
    notify_escalation — a lead is a sales opportunity, not a bot failure,
    and needs to stand out to the owner as higher priority than an FAQ miss."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[PRIORITY LEAD][{tenant.tenant_id}] Customer {customer_phone}: {label}")

    if _settings.smtp_user and _settings.smtp_password:
        _send_email(tenant, customer_phone, label, timestamp)

    _send_lead_whatsapp(tenant, customer_phone, label, timestamp)


def notify_media(tenant, customer_phone: str, media_type: str, media_id: str, caption: str = ""):
    """Forward a customer's uploaded photo/file straight to the tenant's
    WhatsApp. Falls back to an email alert (without the file — Meta's media
    URLs expire, so we can't retrieve a copy after the fact) if forwarding
    fails."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[MEDIA][{tenant.tenant_id}] Customer {customer_phone} sent a {media_type} (id={media_id})")

    try:
        label = f"📎 Attachment from +{customer_phone}"
        if caption:
            label += f": {caption}"
        whatsapp.forward_media(
            whatsapp.creds_for(tenant), tenant.escalation_whatsapp_to, media_type, media_id, label
        )
        return
    except Exception as e:
        print(f"[ERROR] Forwarding media failed: {type(e).__name__}: {e}")

    if _settings.smtp_user and _settings.smtp_password:
        note = f"[Customer uploaded a {media_type} — forward via WhatsApp media id {media_id}]"
        _send_email(tenant, customer_phone, note, timestamp)


def _send_email(tenant, customer_phone: str, question: str, timestamp: str):
    try:
        subject = f"⚠️ {tenant.business_name} bot: customer question needs attention"
        body = f"""
A customer question was escalated (the bot couldn't answer).

Business: {tenant.business_name}
Customer phone: {customer_phone}
Question: {question}
Time: {timestamp}

Please reach out to the customer to help them. You can reply to this customer via WhatsApp at {customer_phone}.
        """.strip()

        msg = MIMEMultipart()
        msg["From"] = _settings.smtp_user
        msg["To"] = tenant.escalation_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(_settings.smtp_host, _settings.smtp_port) as server:
            server.starttls()
            server.login(_settings.smtp_user, _settings.smtp_password)
            server.send_message(msg)
    except Exception as e:
        print(f"[ERROR] Email notification failed: {type(e).__name__}: {e}")


def _send_alert(tenant, to: str, template_params: list[str], fallback_text: str, kind: str, timestamp: str):
    """Try the approved 'escalation_alert_v2' template first — templates
    bypass the 24-hour customer-service window, so they work even if the
    owner hasn't recently messaged the bot. Fall back to free-form text
    (only valid inside the 24h window) if the template fails."""
    global last_error, last_attempt
    last_attempt = f"{kind} tenant={tenant.tenant_id} to={to} at={timestamp}"

    try:
        creds = whatsapp.creds_for(tenant)
    except RuntimeError as e:
        last_error = f"{type(e).__name__}: {e}"
        print(f"[ERROR] {kind} WhatsApp notification skipped: {e}")
        return

    try:
        result = whatsapp.send_template(creds, to, "escalation_alert_v2", template_params)
        last_error = f"SUCCESS (template): {result}"
        return
    except Exception as e:
        print(f"[WARN] {kind} template send failed, falling back to free text: {e}")

    try:
        result = whatsapp.send_message(creds, to, fallback_text)
        last_error = f"SUCCESS (fallback text): {result}"
    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"
        print(f"[ERROR] {kind} WhatsApp notification failed: {type(e).__name__}: {e}")


def _send_whatsapp(tenant, customer_phone: str, question: str, timestamp: str):
    _send_alert(
        tenant,
        tenant.escalation_whatsapp_to,
        [f"+{customer_phone}", question],
        (
            f"⚠️ Bot escalation ({tenant.business_name})\n\n"
            f"Customer: +{customer_phone}\n"
            f"Q: {question}\n"
            f"Time: {timestamp}\n\n"
            f"Customer needs help — please reply on WhatsApp."
        ),
        kind="ESCALATION",
        timestamp=timestamp,
    )


def _send_lead_whatsapp(tenant, customer_phone: str, label: str, timestamp: str):
    _send_alert(
        tenant,
        tenant.escalation_whatsapp_to,
        [f"+{customer_phone}", label],
        (
            f"🔔 *NEW LEAD* ({tenant.business_name})\n\n"
            f"Customer: +{customer_phone}\n"
            f"{label}\n"
            f"Time: {timestamp}"
        ),
        kind="LEAD",
        timestamp=timestamp,
    )
