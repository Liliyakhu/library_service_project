"""
Centralized timezone utilities to avoid duplication and inconsistency.
"""

import pytz
from django.utils import timezone
from django.conf import settings

# Single source of truth for Kyiv timezone
KYIV_TZ = pytz.timezone(settings.TIME_ZONE)


def kyiv_now():
    """Get current datetime in Kyiv timezone"""
    return timezone.now().astimezone(KYIV_TZ)


def kyiv_today():
    """Get current date in Kyiv timezone"""
    return timezone.localtime(timezone.now(), KYIV_TZ).date()


def to_kyiv_time(dt):
    """Convert any datetime to Kyiv timezone"""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, KYIV_TZ)
    return dt.astimezone(KYIV_TZ)


def normalize_to_date(value):
    """
    Normalize datetime or date to date object.
    Handles both aware datetimes and date objects.
    """
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    return value
