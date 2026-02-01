import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class NotificationManager:
    """Handles all notification channels: email, SMS, etc."""

    def __init__(self):
        self.email_enabled = bool(settings.SMTP_USER and settings.SMTP_PASSWORD)
        self.sms_enabled = bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)
        self._twilio_client = None

    def _get_twilio_client(self):
        """Lazily initialize Twilio client."""
        if self._twilio_client is None and self.sms_enabled:
            try:
                from twilio.rest import Client
                self._twilio_client = Client(
                    settings.TWILIO_ACCOUNT_SID,
                    settings.TWILIO_AUTH_TOKEN
                )
            except ImportError:
                logger.warning("Twilio library not installed, SMS disabled")
                self.sms_enabled = False
        return self._twilio_client

    def send_email(self, subject: str, body: str, html: bool = False) -> bool:
        """Send email notification."""
        if not self.email_enabled:
            logger.debug("Email notifications not configured")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[Stocker Trader] {subject}"
            msg["From"] = settings.SMTP_USER
            msg["To"] = settings.NOTIFICATION_EMAIL

            if html:
                msg.attach(MIMEText(body, "html"))
            else:
                msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)

            logger.info(f"Email sent: {subject}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_sms(self, message: str) -> bool:
        """Send SMS notification via Twilio."""
        if not self.sms_enabled:
            logger.debug("SMS notifications not configured")
            return False

        try:
            client = self._get_twilio_client()
            if client is None:
                return False

            client.messages.create(
                body=f"[Stocker Trader] {message}",
                from_=settings.TWILIO_FROM_NUMBER,
                to=settings.TWILIO_TO_NUMBER
            )
            logger.info(f"SMS sent: {message[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to send SMS: {e}")
            return False

    def notify_trade_entry(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        strategy: str
    ) -> None:
        """Notify about a trade entry."""
        subject = f"Trade Entry: {direction.upper()} {symbol}"
        body = (
            f"Trade Entry\n"
            f"------------\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction.upper()}\n"
            f"Quantity: {quantity}\n"
            f"Price: ${price:.2f}\n"
            f"Strategy: {strategy}\n"
            f"Total: ${quantity * price:.2f}"
        )
        self.send_email(subject, body)
        self.send_sms(f"{direction.upper()} {quantity} {symbol} @ ${price:.2f}")

    def notify_trade_exit(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        pnl: float,
        pnl_percent: float
    ) -> None:
        """Notify about a trade exit."""
        result = "WIN" if pnl > 0 else "LOSS"
        subject = f"Trade Exit: {symbol} - {result}"
        body = (
            f"Trade Exit\n"
            f"----------\n"
            f"Symbol: {symbol}\n"
            f"Quantity: {quantity}\n"
            f"Entry: ${entry_price:.2f}\n"
            f"Exit: ${exit_price:.2f}\n"
            f"P&L: ${pnl:.2f} ({pnl_percent:+.2f}%)\n"
            f"Result: {result}"
        )
        self.send_email(subject, body)
        self.send_sms(f"EXIT {symbol}: ${pnl:+.2f} ({pnl_percent:+.2f}%)")

    def notify_error(self, error_type: str, message: str) -> None:
        """Notify about a critical error."""
        subject = f"ERROR: {error_type}"
        body = f"Error Type: {error_type}\n\nDetails:\n{message}"
        self.send_email(subject, body)
        self.send_sms(f"ERROR: {error_type}")

    def notify_daily_summary(
        self,
        total_trades: int,
        winning_trades: int,
        total_pnl: float,
        portfolio_value: float
    ) -> None:
        """Send daily summary notification."""
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        subject = f"Daily Summary - P&L: ${total_pnl:+.2f}"
        body = (
            f"Daily Trading Summary\n"
            f"====================\n\n"
            f"Total Trades: {total_trades}\n"
            f"Winning Trades: {winning_trades}\n"
            f"Win Rate: {win_rate:.1f}%\n"
            f"Daily P&L: ${total_pnl:+.2f}\n"
            f"Portfolio Value: ${portfolio_value:.2f}"
        )
        self.send_email(subject, body)

    def notify_drawdown_warning(self, current_drawdown: float, limit: float) -> None:
        """Notify about approaching drawdown limit."""
        subject = f"DRAWDOWN WARNING: {current_drawdown:.1%}"
        body = (
            f"Drawdown Warning\n"
            f"================\n\n"
            f"Current Drawdown: {current_drawdown:.1%}\n"
            f"Limit: {limit:.1%}\n\n"
            f"Trading may be halted if drawdown continues."
        )
        self.send_email(subject, body)
        self.send_sms(f"DRAWDOWN WARNING: {current_drawdown:.1%}")

    def notify_trading_halted(self, reason: str) -> None:
        """Notify that trading has been halted."""
        subject = "TRADING HALTED"
        body = f"Trading has been halted.\n\nReason: {reason}"
        self.send_email(subject, body)
        self.send_sms(f"TRADING HALTED: {reason}")

    def notify_strategy_disabled(self, strategy_name: str, reason: str) -> None:
        """Notify that a strategy has been disabled."""
        subject = f"Strategy Disabled: {strategy_name}"
        body = f"Strategy '{strategy_name}' has been disabled.\n\nReason: {reason}"
        self.send_email(subject, body)


notifications = NotificationManager()
