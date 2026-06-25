"""
Send notifications to the shop when the bot escalates (can't answer a question).
Supports email and WhatsApp to the shop owner.
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


def notify_escalation(customer_phone: str, question: str):
    """Alert the shop that a customer asked something the bot couldn't answer."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ESCALATION] Customer {customer_phone} asked: {question}")

    # Email notification
    if _settings.smtp_user and _settings.smtp_password:
        print(f"[ESCALATION] Sending email to {_settings.escalation_email}")
        _send_email(customer_phone, question, timestamp)
    else:
        print("[ESCALATION] Email disabled (no SMTP_USER or SMTP_PASSWORD)")

    # WhatsApp notification (if we have a phone number ID)
    if _settings.whatsapp_phone_number_id:
        print(f"[ESCALATION] Sending WhatsApp to {_settings.escalation_whatsapp_to}")
        _send_whatsapp(customer_phone, question, timestamp)
    else:
        print("[ESCALATION] WhatsApp disabled (no WHATSAPP_PHONE_NUMBER_ID)")


def _send_email(customer_phone: str, question: str, timestamp: str):
    """Send email alert to the shop."""
    try:
        subject = "⚠️ Bot escalation: Customer question needs attention"
        body = f"""
A customer question was escalated (the bot couldn't answer).

Customer phone: {customer_phone}
Question: {question}
Time: {timestamp}

Please reach out to the customer to help them. You can reply to this customer via WhatsApp at {customer_phone}.
        """.strip()

        msg = MIMEMultipart()
        msg["From"] = _settings.smtp_user
        msg["To"] = _settings.escalation_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(_settings.smtp_host, _settings.smtp_port) as server:
            server.starttls()
            server.login(_settings.smtp_user, _settings.smtp_password)
            server.send_message(msg)
    except Exception as e:
        print(f"[ERROR] Email notification failed: {type(e).__name__}: {e}")


def _send_whatsapp(customer_phone: str, question: str, timestamp: str):
    """Send WhatsApp alert to the shop owner.

    Tries the approved 'escalation_alert_v2' template first — templates
    bypass the 24-hour customer-service window, so they work even if the
    shop owner hasn't recently messaged the bot. Falls back to free-form
    text (only works inside the 24h window) if the template isn't
    approved yet or fails for any reason.
    """
    global last_error, last_attempt
    last_attempt = f"to={_settings.escalation_whatsapp_to} at={timestamp}"
    try:
        result = whatsapp.send_template(
            _settings.escalation_whatsapp_to,
            "escalation_alert_v2",
            [f"+{customer_phone}", question],
        )
        last_error = f"SUCCESS (template): {result}"
        return
    except Exception as e:
        print(f"[WARN] Template send failed, falling back to free text: {e}")

    try:
        msg = (
            f"⚠️ Bot escalation\n\n"
            f"Customer: +{customer_phone}\n"
            f"Q: {question}\n"
            f"Time: {timestamp}\n\n"
            f"Customer needs help — please reply on WhatsApp."
        )
        result = whatsapp.send_message(_settings.escalation_whatsapp_to, msg)
        last_error = f"SUCCESS (fallback text): {result}"
    except Exception as e:
        last_error = f"{type(e).__name__}: {e}"
        print(f"[ERROR] WhatsApp notification failed: {type(e).__name__}: {e}")
