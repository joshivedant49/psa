"""
WhatsApp notification helper using Twilio's WhatsApp sandbox / approved sender.

Setup:
    pip install twilio

In settings.py add:
    TWILIO_ACCOUNT_SID   = 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    TWILIO_AUTH_TOKEN    = 'your_auth_token'
    TWILIO_WHATSAPP_FROM = 'whatsapp:+14155238886'   # Twilio sandbox number
    ADMIN_WHATSAPP_TO    = 'whatsapp:+919876543210'  # Academy owner's number
"""

import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def send_enquiry_whatsapp(enquiry) -> bool:
    """
    Send a WhatsApp notification to the admin whenever a new enquiry is submitted.
    Returns True on success, False on failure.
    """
    try:
        from twilio.rest import Client
    except ImportError:
        logger.error("Twilio is not installed. Run: pip install twilio")
        return False

    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
    auth_token  = getattr(settings, 'TWILIO_AUTH_TOKEN',  None)
    from_number = getattr(settings, 'TWILIO_WHATSAPP_FROM', None)
    to_number   = getattr(settings, 'ADMIN_WHATSAPP_TO',  None)

    if not all([account_sid, auth_token, from_number, to_number]):
        logger.warning("Twilio WhatsApp credentials not fully configured in settings.py")
        return False

    message_body = (
        f"🏆 *New Enquiry — Pradip Sports Academy*\n\n"
        f"👤 *Name:*  {enquiry.full_name}\n"
        f"📞 *Phone:* {enquiry.phone}\n"
        f"📧 *Email:* {enquiry.email or '—'}\n"
        f"🏅 *Sport:* {enquiry.sport or '—'}\n"
        f"🔢 *Age:*   {enquiry.age or '—'}\n"
        f"💬 *Message:* {enquiry.message or '—'}\n\n"
        f"🕐 Received: {enquiry.created_at.strftime('%d %b %Y, %I:%M %p')}\n"
        f"👉 Login to admin to follow up."
    )

    try:
        client = Client(account_sid, auth_token)
        msg = client.messages.create(
            body=message_body,
            from_=from_number,
            to=to_number,
        )
        logger.info(f"WhatsApp sent successfully. SID: {msg.sid}")
        return True
    except Exception as exc:
        logger.error(f"WhatsApp send failed: {exc}")
        return False
