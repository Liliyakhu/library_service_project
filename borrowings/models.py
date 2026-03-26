from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from datetime import datetime

from books.models import Book


class Borrowing(models.Model):
    borrow_date = models.DateField(default=timezone.now)
    expected_return_date = models.DateField()
    actual_return_date = models.DateField(null=True, blank=True)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="borrowings")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="borrowings"
    )

    class Meta:
        ordering = ["-borrow_date"]
        verbose_name = "Borrowing"
        verbose_name_plural = "Borrowings"

        constraints = [
            # Expected return date must be after borrow date
            models.CheckConstraint(
                check=models.Q(expected_return_date__gt=models.F("borrow_date")),
                name="expected_return_after_borrow",
            ),
            # Actual return date must be on or after borrow date (if not null)
            models.CheckConstraint(
                check=models.Q(actual_return_date__isnull=True)
                | models.Q(actual_return_date__gte=models.F("borrow_date")),
                name="actual_return_after_borrow",
            ),
            # Expected return date should not be more than 1 year from borrow date
            models.CheckConstraint(
                check=models.Q(
                    expected_return_date__lte=models.F("borrow_date")
                    + timezone.timedelta(days=365)
                ),
                name="expected_return_within_year",
            ),
        ]

    def clean(self):
        super().clean()

        # Normalize to date
        if isinstance(self.borrow_date, datetime):
            self.borrow_date = self.borrow_date.date()
        if isinstance(self.expected_return_date, datetime):
            self.expected_return_date = self.expected_return_date.date()
        if isinstance(self.actual_return_date, datetime):
            self.actual_return_date = self.actual_return_date.date()

        # Validate borrow_date is not in the future
        if self.borrow_date and self.borrow_date > timezone.now().date():
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

        # Check if book is available
        if not self.pk and self.book and not self.book.is_available:
            raise ValidationError(
                {"book": "This book is currently not available for borrowing."}
            )

    def save(self, *args, **kwargs):
        """Override save to handle inventory and validation"""
        is_new = self.pk is None
        old_actual_return_date = None

        # Get old actual_return_date if updating
        if not is_new:
            old_borrowing = Borrowing.objects.get(pk=self.pk)
            old_actual_return_date = old_borrowing.actual_return_date

        # Validate the model
        self.clean()

        # Handle inventory changes
        if is_new:
            # New borrowing - decrease inventory
            if not self.book.borrow():
                raise ValidationError("Book is not available for borrowing.")
        else:
            # Existing borrowing - handle return
            if old_actual_return_date is None and self.actual_return_date is not None:
                # Book is being returned
                self.book.return_book()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.full_name} borrowed {self.book.title} on {self.borrow_date}, id = {self.id}"

    @property
    def is_returned(self):
        """Check if the book has been returned"""
        return self.actual_return_date is not None

    @property
    def is_overdue(self):
        """Check if borrowing is overdue (only when no actual_return_date)."""
        if self.actual_return_date:
            return False
        expected = (
            self.expected_return_date.date()
            if isinstance(self.expected_return_date, datetime)
            else self.expected_return_date
        )
        return timezone.now().date() > expected

    @property
    def days_overdue(self):
        """Return positive overdue days, or 0 if not overdue."""
        if not self.is_overdue:
            return 0
        expected = (
            self.expected_return_date.date()
            if isinstance(self.expected_return_date, datetime)
            else self.expected_return_date
        )
        return max((timezone.now().date() - expected).days, 0)

    @property
    def borrowing_days(self):
        """Calculate total borrowing days"""
        end_date = self.actual_return_date or timezone.now().date()
        return (
            end_date - self.borrow_date
        ).days + 1  # +1 to include both start and end days

    @property
    def total_fee(self):
        """Calculate total borrowing fee"""
        return self.book.daily_fee * self.borrowing_days

    def return_book(self, return_date=None):
        """Mark the book as returned with validation"""
        if self.actual_return_date:
            raise ValidationError("Book has already been returned.")

        return_date = return_date or timezone.now().date()

        # Validate return date
        if return_date < self.borrow_date:
            raise ValidationError("Return date cannot be before borrow date.")

        if return_date > timezone.now().date():
            raise ValidationError("Return date cannot be in the future.")

        self.actual_return_date = return_date
        self.save()  # This will trigger inventory updatesave()
