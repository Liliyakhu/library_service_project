import requests
from django.conf import settings


API_URL = "https://api.telegram.org/bot{token}/{method}"


def send_telegram_message(
    text: str,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = True,
    disable_notification: bool = False,
) -> bool:
    """
    Sends a message to the configured chat. Returns True on success, False otherwise.
    Safe to call even if disabled/misconfigured (fails closed & quietly).
    """
    if not getattr(settings, "TELEGRAM_NOTIFICATIONS_ENABLED", False):
        return False

    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        return False

    url = API_URL.format(token=token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
        "disable_notification": disable_notification,
    }

    try:
        resp = requests.post(url, json=payload, timeout=6)
        resp.raise_for_status()
        data = resp.json()
        return bool(data.get("ok"))
    except requests.RequestException:
        return False
