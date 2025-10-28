"""
Centralized timezone utilities to avoid duplication and inconsistency.
"""

import pytz
from django.utils import timezone
from django.conf import settings

# Single source of truth for Kyiv timezone
KYIV_TZ = pytz.timezone(settings.TIME_ZONE)


def kyiv_now():
    """
    Get current datetime in Kyiv timezone.

    Returns:
        datetime: Current time in Kyiv timezone

    Example:
        >>> now = kyiv_now()
        >>> print(now.tzinfo)  # Europe/Kyiv
    """
    return timezone.now().astimezone(KYIV_TZ)


def kyiv_today():
    """
    Get current date in Kyiv timezone.

    Returns:
        date: Current date in Kyiv timezone

    Example:
        >>> today = kyiv_today()
        >>> print(type(today))  # <class 'datetime.date'>
    """
    return timezone.localtime(timezone.now(), KYIV_TZ).date()


def to_kyiv_time(dt):
    """
    Convert any datetime to Kyiv timezone.

    Args:
        dt: datetime object (aware or naive)

    Returns:
        datetime: Datetime in Kyiv timezone or None if input is None

    Example:
        >>> import datetime
        >>> utc_time = datetime.datetime.now(pytz.UTC)
        >>> kyiv_time = to_kyiv_time(utc_time)
    """
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, KYIV_TZ)
    return dt.astimezone(KYIV_TZ)


def normalize_to_date(value):
    """
    Normalize datetime or date to date object.

    Handles both aware datetimes and date objects.
    Useful for comparing dates from different sources.

    Args:
        value: datetime, date, or None

    Returns:
        date: Date object or None if input is None

    Example:
        >>> from django.utils import timezone
        >>> now = timezone.now()
        >>> date_only = normalize_to_date(now)
        >>> print(type(date_only))  # <class 'datetime.date'>
    """
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    return value
