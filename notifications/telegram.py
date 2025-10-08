import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Constants
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_TIMEOUT = 10  # seconds
MAX_MESSAGE_LENGTH = 4096  # Telegram's limit


def send_telegram_message(
    text: str,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = True,
    disable_notification: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> bool:
    """
    Sends a message to the configured chat.

    Args:
        text: Message text
        parse_mode: Parse mode (HTML, Markdown, or None)
        disable_web_page_preview: Disable link previews
        disable_notification: Send silently
        timeout: Request timeout in seconds

    Returns:
        bool: True on success, False otherwise

    Note:
        This function logs all errors instead of silently failing.
    """
    if not getattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", False):
        logger.debug("Telegram notifications disabled")
        return False

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.error(
            "Telegram notifications enabled but BOT_TOKEN or CHAT_ID not configured"
        )
        return False

    # Validate message length
    if len(text) > MAX_MESSAGE_LENGTH:
        logger.warning(
            f"Message too long ({len(text)} chars), truncating to {MAX_MESSAGE_LENGTH}"
        )
        text = text[: MAX_MESSAGE_LENGTH - 3] + "..."

    url = TELEGRAM_API_URL.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
        "disable_notification": disable_notification,
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        if data.get("ok"):
            logger.info("Telegram message sent successfully")
            return True
        else:
            logger.error(f"Telegram API returned ok=False: {data}")
            return False

    except requests.Timeout:
        logger.error(f"Telegram request timed out after {timeout}s")
        return False
    except requests.HTTPError as e:
        logger.error(
            f"Telegram HTTP error: {e.response.status_code} - {e.response.text}"
        )
        return False
    except requests.RequestException as e:
        logger.error(f"Telegram request failed: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending Telegram message: {str(e)}")
        return False


def send_telegram_message_with_retry(text: str, max_retries: int = 3, **kwargs) -> bool:
    """
    Send Telegram message with retry logic.

    Args:
        text: Message text
        max_retries: Maximum number of retry attempts
        **kwargs: Additional arguments for send_telegram_message

    Returns:
        bool: True if successful, False after all retries fail
    """
    for attempt in range(max_retries):
        if send_telegram_message(text, **kwargs):
            return True

        if attempt < max_retries - 1:
            logger.warning(f"Telegram send failed, retry {attempt + 1}/{max_retries}")

    logger.error(f"Telegram send failed after {max_retries} attempts")
    return False
