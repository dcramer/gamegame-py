"""Email service tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gamegame.services.email import (
    ConsoleEmailBackend,
    EmailService,
    ResendEmailBackend,
    SMTPEmailBackend,
    get_email_backend,
)


class TestConsoleEmailBackend:
    """Tests for console email backend."""

    @pytest.mark.asyncio
    async def test_send_logs_email(self, caplog):
        """Test that console backend logs the email."""
        import logging

        backend = ConsoleEmailBackend()

        with caplog.at_level(logging.INFO):
            result = await backend.send(
                to="test@example.com",
                subject="Test Subject",
                html="<p>Hello</p>",
                text="Hello",
            )

        assert result is True
        assert "test@example.com" in caplog.text
        assert "Test Subject" in caplog.text

    @pytest.mark.asyncio
    async def test_send_without_text(self):
        """Test sending without plain text falls back to HTML."""
        backend = ConsoleEmailBackend()

        result = await backend.send(
            to="test@example.com",
            subject="Test",
            html="<p>HTML content</p>",
        )

        assert result is True


class TestSMTPEmailBackend:
    """Tests for SMTP email backend."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Test successful SMTP send."""
        backend = SMTPEmailBackend(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            from_address="noreply@example.com",
        )

        with patch("gamegame.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await backend.send(
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
                text="Hello",
            )

            assert result is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure(self):
        """Test SMTP send failure."""
        backend = SMTPEmailBackend(
            host="smtp.example.com",
            port=587,
            username="user",
            password="pass",
            from_address="noreply@example.com",
        )

        with patch(
            "gamegame.services.email.aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=Exception("Connection failed"),
        ):
            result = await backend.send(
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
            )

            assert result is False


class TestResendEmailBackend:
    """Tests for Resend email backend."""

    @pytest.mark.asyncio
    async def test_send_success(self):
        """Test successful Resend send."""
        backend = ResendEmailBackend(
            api_key="re_test_key",
            from_address="noreply@example.com",
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await backend.send(
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
                text="Hello",
            )

            assert result is True
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            assert call_kwargs["json"]["to"] == ["test@example.com"]
            assert call_kwargs["json"]["subject"] == "Test"

    @pytest.mark.asyncio
    async def test_send_http_error(self):
        """Test Resend HTTP error handling."""
        backend = ResendEmailBackend(
            api_key="re_test_key",
            from_address="noreply@example.com",
        )

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await backend.send(
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_send_network_error(self):
        """Test Resend network error handling."""
        backend = ResendEmailBackend(
            api_key="re_test_key",
            from_address="noreply@example.com",
        )

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=Exception("Network error"),
        ):
            result = await backend.send(
                to="test@example.com",
                subject="Test",
                html="<p>Hello</p>",
            )

            assert result is False


class TestGetEmailBackend:
    """Tests for get_email_backend factory."""

    def test_console_backend(self):
        """Test console backend selection."""
        with patch("gamegame.services.email.settings") as mock_settings:
            mock_settings.email_backend = "console"

            backend = get_email_backend()

            assert isinstance(backend, ConsoleEmailBackend)

    def test_smtp_backend(self):
        """Test SMTP backend selection."""
        with patch("gamegame.services.email.settings") as mock_settings:
            mock_settings.email_backend = "smtp"
            mock_settings.smtp_host = "smtp.example.com"
            mock_settings.smtp_port = 587
            mock_settings.smtp_username = "user"
            mock_settings.smtp_password = "pass"
            mock_settings.smtp_use_tls = True
            mock_settings.email_from = "noreply@example.com"

            backend = get_email_backend()

            assert isinstance(backend, SMTPEmailBackend)
            assert backend.host == "smtp.example.com"

    def test_resend_backend(self):
        """Test Resend backend selection."""
        with patch("gamegame.services.email.settings") as mock_settings:
            mock_settings.email_backend = "resend"
            mock_settings.resend_api_key = "re_test_key"
            mock_settings.email_from = "noreply@example.com"

            backend = get_email_backend()

            assert isinstance(backend, ResendEmailBackend)
            assert backend.api_key == "re_test_key"

    def test_invalid_backend(self):
        """Test invalid backend raises error."""
        with patch("gamegame.services.email.settings") as mock_settings:
            mock_settings.email_backend = "invalid"

            with pytest.raises(ValueError, match="Unknown email backend"):
                get_email_backend()


class TestEmailService:
    """Tests for EmailService."""

    @pytest.mark.asyncio
    async def test_send_magic_link(self):
        """Test sending magic link email."""
        mock_backend = AsyncMock()
        mock_backend.send.return_value = True

        service = EmailService(backend=mock_backend)

        result = await service.send_magic_link(
            to="test@example.com",
            magic_link="http://localhost:5173/auth/verify?token=abc123",
        )

        assert result is True
        mock_backend.send.assert_called_once()

        call_kwargs = mock_backend.send.call_args[1]
        assert call_kwargs["to"] == "test@example.com"
        assert call_kwargs["subject"] == "Sign in to GameGame"
        assert "abc123" in call_kwargs["html"]
        assert "abc123" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_send_magic_link_failure(self):
        """Test magic link email failure."""
        mock_backend = AsyncMock()
        mock_backend.send.return_value = False

        service = EmailService(backend=mock_backend)

        result = await service.send_magic_link(
            to="test@example.com",
            magic_link="http://localhost:5173/auth/verify?token=abc123",
        )

        assert result is False

    def test_lazy_backend_loading(self):
        """Test that backend is lazy-loaded."""
        service = EmailService()

        with patch("gamegame.services.email.get_email_backend") as mock_get_backend:
            mock_get_backend.return_value = ConsoleEmailBackend()

            # Access backend property
            backend = service.backend

            assert isinstance(backend, ConsoleEmailBackend)
            mock_get_backend.assert_called_once()

            # Second access should not call factory again
            backend2 = service.backend
            assert backend is backend2
            mock_get_backend.assert_called_once()
