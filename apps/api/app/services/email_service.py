"""Optional SMTP email service for sending invitation emails."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def is_email_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from_email)


def send_invitation_email(
    to: str,
    inviter_email: str,
    project_name: str,
    invite_url: str,
) -> bool:
    """Send an invitation email. Returns True if sent, False if SMTP not configured or failed."""
    if not is_email_configured():
        return False

    subject = f"You've been invited to join {project_name} on Loopwise"
    html = f"""\
<div style="font-family: -apple-system, sans-serif; max-width: 480px; margin: 0 auto;">
  <h2 style="color: #4f46e5;">Loopwise</h2>
  <p>{inviter_email} has invited you to join the project <strong>{project_name}</strong>.</p>
  <p>
    <a href="{invite_url}"
       style="display: inline-block; padding: 10px 24px; background: #4f46e5; color: #fff;
              text-decoration: none; border-radius: 8px; font-weight: 500;">
      Accept Invitation
    </a>
  </p>
  <p style="color: #6b7280; font-size: 13px;">
    Or copy this link: {invite_url}
  </p>
</div>"""

    plain = (
        f"{inviter_email} has invited you to join the project \"{project_name}\" on Loopwise.\n\n"
        f"Accept the invitation: {invite_url}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_email
    msg["To"] = to
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_from_email, [to], msg.as_string())
        server.quit()
        logger.info("Invitation email sent to %s", to)
        return True
    except Exception:
        logger.exception("Failed to send invitation email to %s", to)
        return False
