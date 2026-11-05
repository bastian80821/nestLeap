"""Push notifications (optional). NOTIFY_URL may be any ntfy-compatible endpoint,
e.g. https://ntfy.sh/<long-random-topic> — install the ntfy app and subscribe to it."""

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


def notify(title: str, message: str, level: str = "info") -> None:
    log = logger.error if level == "error" else logger.warning if level == "warning" else logger.info
    log(f"[notify] {title}: {message}")
    if not settings.notify_url:
        return
    try:
        httpx.post(
            settings.notify_url,
            content=message.encode(),
            headers={
                "Title": f"NestLeap: {title}",
                "Priority": "high" if level == "error" else "default",
                "Tags": {"error": "rotating_light", "warning": "warning"}.get(level, "chart_with_upwards_trend"),
            },
            timeout=10,
        )
    except Exception as e:  # never let a notification failure break trading logic
        logger.warning(f"Notification failed: {e}")
