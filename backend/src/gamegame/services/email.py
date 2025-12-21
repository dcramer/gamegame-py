"""Email service for sending transactional emails."""

import logging
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import httpx

from gamegame.config import settings

logger = logging.getLogger(__name__)


class EmailBackend(ABC):
    """Abstract base class for email backends."""

    @abstractmethod
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
    ) -> bool:
        """Send an email.

        Args:
            to: Recipient email address
            subject: Email subject
            html: HTML content
            text: Plain text content (optional, derived from html if not provided)

        Returns:
            True if sent successfully
        """
        pass


class ConsoleEmailBackend(EmailBackend):
    """Email backend that logs to console (for development)."""

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
    ) -> bool:
        """Log email to console instead of sending."""
        logger.info(
            f"\n{'='*60}\n"
            f"EMAIL (console backend - not sent)\n"
            f"{'='*60}\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"{'='*60}\n"
            f"{text or html}\n"
            f"{'='*60}\n"
        )
        return True


class SMTPEmailBackend(EmailBackend):
    """Email backend using SMTP."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool = True,
        from_address: str = "",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_address = from_address

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
    ) -> bool:
        """Send email via SMTP."""
        message = MIMEMultipart("alternative")
        message["From"] = self.from_address
        message["To"] = to
        message["Subject"] = subject

        # Add plain text part
        if text:
            message.attach(MIMEText(text, "plain"))

        # Add HTML part
        message.attach(MIMEText(html, "html"))

        try:
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )
            logger.info(f"Email sent via SMTP to {to}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email via SMTP to {to}: {e}")
            return False


class ResendEmailBackend(EmailBackend):
    """Email backend using Resend API."""

    def __init__(self, api_key: str, from_address: str):
        self.api_key = api_key
        self.from_address = from_address

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
    ) -> bool:
        """Send email via Resend API."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": self.from_address,
                        "to": [to],
                        "subject": subject,
                        "html": html,
                        "text": text,
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                logger.info(f"Email sent via Resend to {to}")
                return True
            except httpx.HTTPStatusError as e:
                logger.error(f"Resend API error: {e.response.status_code} - {e.response.text}")
                return False
            except Exception as e:
                logger.error(f"Failed to send email via Resend to {to}: {e}")
                return False


def get_email_backend() -> EmailBackend:
    """Get the configured email backend."""
    if settings.email_backend == "console":
        return ConsoleEmailBackend()
    elif settings.email_backend == "smtp":
        return SMTPEmailBackend(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            from_address=settings.email_from,
        )
    elif settings.email_backend == "resend":
        return ResendEmailBackend(
            api_key=settings.resend_api_key,
            from_address=settings.email_from,
        )
    else:
        raise ValueError(f"Unknown email backend: {settings.email_backend}")


class EmailService:
    """High-level email service for sending application emails."""

    def __init__(self, backend: EmailBackend | None = None):
        self._backend = backend

    @property
    def backend(self) -> EmailBackend:
        """Lazy-load the backend."""
        if self._backend is None:
            self._backend = get_email_backend()
        return self._backend

    async def send_magic_link(self, to: str, magic_link: str) -> bool:
        """Send a magic link authentication email.

        Args:
            to: Recipient email address
            magic_link: The full magic link URL

        Returns:
            True if sent successfully
        """
        subject = "Sign in to GameGame"

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="text-align: center; margin-bottom: 30px;">
        <h1 style="color: #1a1a1a; margin: 0;">🎲 GameGame</h1>
    </div>

    <div style="background: #f9fafb; border-radius: 8px; padding: 30px; margin-bottom: 30px;">
        <h2 style="margin-top: 0; color: #1a1a1a;">Sign in to your account</h2>
        <p>Click the button below to sign in to GameGame. This link will expire in {settings.magic_link_expiration_minutes} minutes.</p>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{magic_link}"
               style="background: #2563eb; color: white; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: 500; display: inline-block;">
                Sign in to GameGame
            </a>
        </div>

        <p style="color: #666; font-size: 14px;">
            If you didn't request this email, you can safely ignore it.
        </p>
    </div>

    <div style="text-align: center; color: #666; font-size: 12px;">
        <p>
            If the button doesn't work, copy and paste this link into your browser:<br>
            <a href="{magic_link}" style="color: #2563eb; word-break: break-all;">{magic_link}</a>
        </p>
    </div>
</body>
</html>
"""

        text = f"""
Sign in to GameGame
==================

Click the link below to sign in to your account.
This link will expire in {settings.magic_link_expiration_minutes} minutes.

{magic_link}

If you didn't request this email, you can safely ignore it.
"""

        return await self.backend.send(to=to, subject=subject, html=html, text=text)


# Global email service instance
email_service = EmailService()
