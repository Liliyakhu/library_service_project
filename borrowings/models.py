import logging
from django.db import models, transaction
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal

from books.models import Book
from core.utils.timezone_utils import KYIV_TZ, kyiv_today, normalize_to_date

logger = logging.getLogger(__name__)


class Borrowing(models.Model):
    borrow_date = models.DateField(default=kyiv_today)
    expected_return_date = models.DateField()
    actual_return_date = models.DateField(null=True, blank=True)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="borrowings")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="borrowings",
    )

    class Meta:
        ordering = ["-borrow_date"]
        verbose_name = "Borrowing"
        verbose_name_plural = "Borrowings"

        constraints = [
            # Expected return date must be after borrow date
            models.CheckConstraint(
                condition=models.Q(expected_return_date__gt=models.F("borrow_date")),
                name="expected_return_after_borrow",
            ),
            # Actual return date must be on or after borrow date (if not null)
            models.CheckConstraint(
                condition=models.Q(actual_return_date__isnull=True)
                | models.Q(actual_return_date__gte=models.F("borrow_date")),
                name="actual_return_after_borrow",
            ),
            # Expected return date should not be more than 1 year from borrow date
            models.CheckConstraint(
                condition=models.Q(
                    expected_return_date__lte=models.F("borrow_date")
                    + timezone.timedelta(days=365)
                ),
                name="expected_return_within_year",
            ),
            # Prevent multiple active borrowings of same book by same user
            models.UniqueConstraint(
                fields=["user", "book"],
                condition=models.Q(actual_return_date__isnull=True),
                name="unique_active_borrowing_per_user_book",
            ),
        ]

        indexes = [
            models.Index(fields=["user", "actual_return_date"]),
            models.Index(fields=["expected_return_date", "actual_return_date"]),
            models.Index(fields=["book", "actual_return_date"]),
        ]

    def clean(self):
        super().clean()

        # Normalize dates
        self.borrow_date = normalize_to_date(self.borrow_date)
        self.expected_return_date = normalize_to_date(self.expected_return_date)
        self.actual_return_date = normalize_to_date(self.actual_return_date)

        # Validate borrow_date is not in the future
        if self.borrow_date and self.borrow_date > kyiv_today():
            raise ValidationError(
                {"borrow_date": "Borrow date cannot be in the future."}
            )

        # Validate expected_return_date is after borrow_date
        if self.borrow_date and self.expected_return_date:
            if self.expected_return_date <= self.borrow_date:
                raise ValidationError(
                    {
                        "expected_return_date": "Expected return date must be after borrow date."
                    }
                )

        # Validate actual_return_date is not before borrow_date
        if self.actual_return_date and self.borrow_date:
            if self.actual_return_date < self.borrow_date:
                raise ValidationError(
                    {
                        "actual_return_date": "Actual return date cannot be before borrow date."
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()

        is_new = self.pk is None
        old_actual_return_date = None

        # Get old actual_return_date if updating
        if not is_new:
            try:
                old_borrowing = Borrowing.objects.get(pk=self.pk)
                old_actual_return_date = old_borrowing.actual_return_date
            except Borrowing.DoesNotExist:
                logger.error(f"Borrowing with pk {self.pk} not found during update")
                raise

        # Handle inventory changes
        if is_new:
            # New borrowing - decrease inventory
            if not self.book.borrow():
                raise ValidationError("Book is not available for borrowing.")
            logger.info(f"Created borrowing {self.pk} for book {self.book.id}")
        else:
            # Existing borrowing - handle return
            if old_actual_return_date is None and self.actual_return_date is not None:
                # Book is being returned
                self.book.return_book()
                logger.info(f"Returned book {self.book.id} for borrowing {self.pk}")

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.full_name} borrowed {self.book.title} on {self.borrow_date}, id = {self.id}"

    @property
    def is_returned(self):
        """Check if the book has been returned"""
        return self.actual_return_date is not None

    @property
    def is_active(self):
        """Check if borrowing is currently active"""
        return self.actual_return_date is None

    @property
    def is_overdue(self):
        """Check if borrowing is currently overdue (active borrowings only)."""
        if self.actual_return_date is not None:
            return False  # Returned books are not "currently overdue"

        expected = normalize_to_date(self.expected_return_date)
        return kyiv_today() > expected

    @property
    def was_returned_late(self):
        """Check if book was returned after the expected date."""
        if not self.actual_return_date:
            return False

        expected = normalize_to_date(self.expected_return_date)
        actual = normalize_to_date(self.actual_return_date)
        return actual > expected

    @property
    def needs_fine_payment(self):
        """
        Check if this borrowing needs a fine payment.
        Check for unpaid fines specifically, not just existence.
        """
        if not self.was_returned_late:
            return False

        # Check if there's a paid fine
        paid_fine = self.payments.filter(type="fine", status="paid").exists()
        if paid_fine:
            return False

        # Check if there's a pending fine
        pending_fine = self.payments.filter(type="fine", status="pending").exists()
        return not pending_fine

    @property
    def borrowing_days(self):
        """Planned borrowing duration (without overdue days)."""
        return (self.expected_return_date - self.borrow_date).days

    @property
    def payment_fee(self):
        """Base borrowing fee (without fine)."""
        return (self.book.daily_fee * self.borrowing_days).quantize(Decimal("0.01"))

    @property
    def fine_fee(self):
        """Calculate fine amount for late return."""
        if not self.was_returned_late:
            return Decimal("0.00")

        fine_multiplier = Decimal(str(getattr(settings, "FINE_MULTIPLIER", 2.0)))
        expected = normalize_to_date(self.expected_return_date)
        actual = normalize_to_date(self.actual_return_date)

        days_late = (actual - expected).days
        if days_late <= 0:
            return Decimal("0.00")

        daily_fee = self.book.daily_fee
        fine_amount = days_late * daily_fee * fine_multiplier
        return fine_amount.quantize(Decimal("0.01"))

    @property
    def total_amount_due(self):
        """Total amount including normal fee and fine if overdue."""
        return (self.payment_fee + self.fine_fee).quantize(Decimal("0.01"))

    @property
    def days_overdue(self):
        """Number of days overdue (0 if returned on time or not overdue)."""
        expected = normalize_to_date(self.expected_return_date)

        if self.actual_return_date:
            actual = normalize_to_date(self.actual_return_date)
            return max((actual - expected).days, 0)

        # Not returned yet → calculate relative to today
        if kyiv_today() > expected:
            return (kyiv_today() - expected).days
        return 0

    @transaction.atomic
    def return_book(self, return_date=None):
        """Mark the book as returned with validation"""
        if self.actual_return_date:
            raise ValidationError("Book has already been returned.")

        return_date = return_date or kyiv_today()

        # Validate return date
        if return_date < self.borrow_date:
            raise ValidationError("Return date cannot be before borrow date.")

        if return_date > kyiv_today():
            raise ValidationError("Return date cannot be in the future.")

        self.actual_return_date = return_date
        self.save()  # This will trigger inventory update

        logger.info(
            f"Borrowing {self.id} returned on {return_date}. "
            f"Was late: {self.was_returned_late}"
        )
