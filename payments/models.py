import logging
from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from borrowings.models import Borrowing
from core.utils.timezone_utils import kyiv_now

logger = logging.getLogger(__name__)


class Payment(models.Model):
    """
    Payment model for borrowing fees and fines.

    Status flow:
        pending -> paid (successful payment)
        pending -> expired (session timeout)
        expired -> pending (session renewal)
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("expired", "Expired"),
    ]

    TYPE_CHOICES = [
        ("payment", "Payment"),
        ("fine", "Fine"),
    ]

    status = models.CharField(
        max_length=7,
        choices=STATUS_CHOICES,
        default="pending",
    )
    type = models.CharField(
        max_length=7,
        choices=TYPE_CHOICES,
        default="payment",
    )
    borrowing = models.ForeignKey(
        Borrowing, on_delete=models.CASCADE, related_name="payments"
    )
    session_url = models.URLField(max_length=500, blank=True, null=True)
    session_id = models.CharField(max_length=255, blank=True, null=True)
    money_to_pay = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("0.00")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    session_expires_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Ensure money_to_pay is positive
            models.CheckConstraint(
                condition=models.Q(money_to_pay__gt=0), name="positive_money_to_pay"
            ),
            # Unique session_id when not null
            models.UniqueConstraint(
                fields=["session_id"],
                condition=models.Q(session_id__isnull=False),
                name="unique_session_id",
            ),
            # Only one paid payment per type per borrowing
            models.UniqueConstraint(
                fields=["borrowing", "type"],
                condition=models.Q(status="paid"),
                name="unique_paid_payment_per_type",
            ),
        ]

        indexes = [
            models.Index(fields=["status", "session_expires_at"]),
            models.Index(fields=["borrowing", "type", "status"]),
            models.Index(fields=["session_id"]),
        ]

    def clean(self):
        """Validate payment data."""
        super().clean()

        # Validate that session_url and session_id are both present or both absent
        if bool(self.session_url) != bool(self.session_id):
            raise ValidationError(
                "session_url and session_id must be both provided or both empty"
            )

        # Validate that paid payments have session data
        if self.status == "paid" and (not self.session_url or not self.session_id):
            raise ValidationError("Paid payments must have session_url and session_id")

        # Validate money_to_pay is positive
        if self.money_to_pay <= 0:
            raise ValidationError("Payment amount must be greater than zero")

    def save(self, *args, **kwargs):
        """Save with validation and auto-set expiration."""
        # Run validation first
        self.full_clean()

        # Set session expiration time when session is first created
        if self.session_id and not self.session_expires_at:
            self.session_expires_at = kyiv_now() + timezone.timedelta(
                hours=settings.STRIPE_SESSION_EXPIRY_HOURS
            )
            logger.info(
                f"Payment {self.pk}: Session expires at {self.session_expires_at}"
            )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment {self.id} - {self.get_status_display()} - ${self.money_to_pay}"

    # ==================== Status Properties ====================

    @property
    def is_paid(self):
        """Check if payment is completed"""
        return self.status == "paid"

    @property
    def is_expired(self):
        """Check if payment session is expired"""
        if self.status == "expired":
            return True
        if self.session_expires_at and kyiv_now() > self.session_expires_at:
            return True
        return False

    @property
    def is_renewable(self):
        """
        Check if payment can be renewed.

        Returns:
            bool: True if not paid and (expired or missing/expired session)
        """
        return self.status != "paid" and (
            self.status == "expired" or self.session_id is None or self.is_expired
        )

    # ==================== Action Methods ====================

    def expire_session(self):
        """
        Mark payment session as expired

        Only updates if currently pending.
        """
        if self.status == "pending":
            old_status = self.status
            self.status = "expired"
            self.save()
            logger.info(
                f"Payment {self.id}: Status changed from {old_status} to expired"
            )

    def renew_session(self, new_session_id, new_session_url):
        """
        Renew payment session with new Stripe session data.

        Args:
            new_session_id: New Stripe session ID
            new_session_url: New checkout URL

        Raises:
            ValidationError: If payment is not renewable
        """
        if not self.is_renewable:
            raise ValidationError("Payment is not renewable")

        self.session_id = new_session_id
        self.session_url = new_session_url
        self.session_expires_at = kyiv_now() + timezone.timedelta(
            hours=settings.STRIPE_SESSION_EXPIRY_HOURS
        )
        self.status = "pending"
        self.save()

        logger.info(
            f"Payment {self.id}: Session renewed. "
            f"New expiry: {self.session_expires_at}"
        )
