"""
Notification Sending Service

Handles actual delivery of notifications through various channels:
- EMAIL: SMTP email delivery
- SMS: Twilio integration (placeholder for other providers)
- WEBHOOK: HTTP POST requests
- SLACK: Slack webhook integration
- TELEGRAM: Telegram bot API
- WHATSAPP: WhatsApp Business API (placeholder)
"""
import logging
import smtplib
import httpx
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from datetime import datetime

from app.core.metrics import track_notification_sent

logger = logging.getLogger("router.notification_sender")


class NotificationSender:
    """Base notification sender with channel-specific implementations"""

    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def send(
        self,
        channel_type: str,
        channel_config: Dict[str, Any],
        recipient: str,
        subject: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send notification through specified channel.

        Args:
            channel_type: Type of channel (EMAIL, SMS, WEBHOOK, etc.)
            channel_config: Channel-specific configuration
            recipient: Target recipient (email, phone, URL)
            subject: Notification subject/title
            message: Notification body/content
            metadata: Additional metadata (event details, etc.)

        Returns:
            Dict with status, delivery_time_ms, and optional error_message
        """
        start_time = datetime.now()

        try:
            if channel_type == "EMAIL":
                await self._send_email(channel_config, recipient, subject, message, metadata)

            elif channel_type == "SMS":
                await self._send_sms(channel_config, recipient, message)

            elif channel_type == "WEBHOOK":
                await self._send_webhook(channel_config, recipient, subject, message, metadata)

            elif channel_type == "SLACK":
                await self._send_slack(channel_config, recipient, subject, message, metadata)

            elif channel_type == "TELEGRAM":
                await self._send_telegram(channel_config, recipient, message)

            elif channel_type == "WHATSAPP":
                await self._send_whatsapp(channel_config, recipient, message)

            else:
                raise ValueError(f"Unsupported channel type: {channel_type}")

            delivery_time_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Track metrics
            track_notification_sent(channel_type, "SENT", delivery_time_ms)

            return {
                "status": "SENT",
                "delivery_time_ms": round(delivery_time_ms, 2),
                "sent_at": datetime.now()
            }

        except Exception as e:
            delivery_time_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.error(f"Failed to send {channel_type} notification to {recipient}: {e}")

            # Track failed notification
            track_notification_sent(channel_type, "FAILED", delivery_time_ms)

            return {
                "status": "FAILED",
                "delivery_time_ms": round(delivery_time_ms, 2),
                "error_message": str(e),
                "sent_at": datetime.now()
            }


    async def _send_email(
        self,
        config: Dict[str, Any],
        recipient: str,
        subject: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Send email via SMTP.

        Expected config:
        {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "alerts@company.com",
            "smtp_password": "app_password",
            "from_email": "VIGIAS Alerts <alerts@company.com>",
            "use_tls": true
        }
        """
        smtp_host = config.get("smtp_host")
        smtp_port = config.get("smtp_port", 587)
        smtp_user = config.get("smtp_user")
        smtp_password = config.get("smtp_password")
        from_email = config.get("from_email", smtp_user)
        use_tls = config.get("use_tls", True)

        if not all([smtp_host, smtp_user, smtp_password]):
            raise ValueError("Missing SMTP configuration (smtp_host, smtp_user, smtp_password)")

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = recipient

        # Plain text version
        text_part = MIMEText(message, "plain", "utf-8")
        msg.attach(text_part)

        # HTML version (optional, enhanced formatting)
        if metadata:
            html_message = self._format_email_html(subject, message, metadata)
            html_part = MIMEText(html_message, "html", "utf-8")
            msg.attach(html_part)

        # Send via SMTP
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if use_tls:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        logger.info(f"Email sent to {recipient}")


    def _format_email_html(self, subject: str, message: str, metadata: Dict[str, Any]) -> str:
        """Format email with HTML styling"""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background-color: #2c3e50; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .footer {{ background-color: #ecf0f1; padding: 10px; text-align: center; font-size: 12px; }}
                .metadata {{ background-color: #f8f9fa; border-left: 4px solid #3498db; padding: 10px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>🔔 {subject}</h2>
            </div>
            <div class="content">
                <p>{message}</p>
                <div class="metadata">
                    <strong>Event Details:</strong><br>
                    <pre>{json.dumps(metadata, indent=2)}</pre>
                </div>
            </div>
            <div class="footer">
                <p>VIGIAS-IA Computer Vision Platform</p>
                <p>This is an automated notification. Please do not reply to this email.</p>
            </div>
        </body>
        </html>
        """


    async def _send_sms(self, config: Dict[str, Any], recipient: str, message: str):
        """
        Send SMS via Twilio (or other provider).

        Expected config:
        {
            "provider": "twilio",
            "account_sid": "ACxxxxxx",
            "auth_token": "your_auth_token",
            "from_number": "+1234567890"
        }
        """
        provider = config.get("provider", "twilio")

        if provider == "twilio":
            account_sid = config.get("account_sid")
            auth_token = config.get("auth_token")
            from_number = config.get("from_number")

            if not all([account_sid, auth_token, from_number]):
                raise ValueError("Missing Twilio configuration")

            # Twilio API endpoint
            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

            # Truncate message to 160 characters for SMS
            sms_message = message[:160]

            response = await self.http_client.post(
                url,
                auth=(account_sid, auth_token),
                data={
                    "From": from_number,
                    "To": recipient,
                    "Body": sms_message
                }
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"Twilio API error: {response.status_code} - {response.text}")

            logger.info(f"SMS sent to {recipient} via Twilio")

        else:
            raise ValueError(f"Unsupported SMS provider: {provider}")


    async def _send_webhook(
        self,
        config: Dict[str, Any],
        url: str,
        subject: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Send webhook HTTP POST.

        Expected config:
        {
            "method": "POST",
            "headers": {"Authorization": "Bearer token"},
            "payload_template": "custom"  # or "standard"
        }
        """
        method = config.get("method", "POST").upper()
        headers = config.get("headers", {})
        payload_template = config.get("payload_template", "standard")

        # Ensure Content-Type is set
        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        # Build payload
        if payload_template == "standard":
            payload = {
                "subject": subject,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {}
            }
        else:
            # Custom template (user can define their own structure)
            payload = {
                "alert": {
                    "title": subject,
                    "body": message,
                    "data": metadata or {}
                }
            }

        # Send request
        if method == "POST":
            response = await self.http_client.post(url, json=payload, headers=headers)
        elif method == "PUT":
            response = await self.http_client.put(url, json=payload, headers=headers)
        else:
            raise ValueError(f"Unsupported webhook method: {method}")

        if response.status_code not in [200, 201, 202, 204]:
            raise Exception(f"Webhook error: {response.status_code} - {response.text}")

        logger.info(f"Webhook sent to {url}")


    async def _send_slack(
        self,
        config: Dict[str, Any],
        webhook_url: str,
        subject: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Send Slack message via webhook.

        Expected config:
        {
            "webhook_url": "https://hooks.slack.com/services/...",
            "username": "VIGIAS Alert Bot",
            "icon_emoji": ":rotating_light:"
        }
        """
        # Use webhook_url from config if recipient is not a full URL
        if not webhook_url.startswith("http"):
            webhook_url = config.get("webhook_url", webhook_url)

        username = config.get("username", "VIGIAS Alert")
        icon_emoji = config.get("icon_emoji", ":warning:")

        # Format Slack message with blocks
        payload = {
            "username": username,
            "icon_emoji": icon_emoji,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"🚨 {subject}"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": message
                    }
                }
            ]
        }

        # Add metadata as attachment if present
        if metadata:
            payload["attachments"] = [{
                "color": "#e74c3c",
                "fields": [
                    {"title": key, "value": str(value), "short": True}
                    for key, value in metadata.items()
                ]
            }]

        response = await self.http_client.post(webhook_url, json=payload)

        if response.status_code != 200:
            raise Exception(f"Slack webhook error: {response.status_code} - {response.text}")

        logger.info(f"Slack notification sent")


    async def _send_telegram(self, config: Dict[str, Any], chat_id: str, message: str):
        """
        Send Telegram message via Bot API.

        Expected config:
        {
            "bot_token": "123456:ABC-DEF...",
            "parse_mode": "Markdown"  # or "HTML"
        }
        """
        bot_token = config.get("bot_token")
        parse_mode = config.get("parse_mode", "Markdown")

        if not bot_token:
            raise ValueError("Missing Telegram bot_token in configuration")

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode
        }

        response = await self.http_client.post(url, json=payload)

        if response.status_code != 200:
            raise Exception(f"Telegram API error: {response.status_code} - {response.text}")

        logger.info(f"Telegram message sent to chat {chat_id}")


    async def _send_whatsapp(self, config: Dict[str, Any], recipient: str, message: str):
        """
        Send WhatsApp message via Business API.

        Expected config:
        {
            "provider": "twilio",  # or "whatsapp_cloud"
            "account_sid": "ACxxxxxx",
            "auth_token": "token",
            "from_number": "whatsapp:+14155238886"
        }

        Note: WhatsApp requires approved message templates for most use cases.
        This is a simplified implementation.
        """
        provider = config.get("provider", "twilio")

        if provider == "twilio":
            account_sid = config.get("account_sid")
            auth_token = config.get("auth_token")
            from_number = config.get("from_number")

            if not all([account_sid, auth_token, from_number]):
                raise ValueError("Missing WhatsApp/Twilio configuration")

            # Ensure WhatsApp prefix
            if not recipient.startswith("whatsapp:"):
                recipient = f"whatsapp:{recipient}"
            if not from_number.startswith("whatsapp:"):
                from_number = f"whatsapp:{from_number}"

            url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"

            response = await self.http_client.post(
                url,
                auth=(account_sid, auth_token),
                data={
                    "From": from_number,
                    "To": recipient,
                    "Body": message
                }
            )

            if response.status_code not in [200, 201]:
                raise Exception(f"WhatsApp API error: {response.status_code} - {response.text}")

            logger.info(f"WhatsApp message sent to {recipient}")

        else:
            raise ValueError(f"Unsupported WhatsApp provider: {provider}")


    async def close(self):
        """Close HTTP client"""
        await self.http_client.aclose()


# Global singleton instance
notification_sender = NotificationSender()
