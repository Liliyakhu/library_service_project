from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator


class CoverType(models.TextChoices):
    HARD = "hard", _("Hard")
    SOFT = "soft", _("Soft")


class Book(models.Model):
    title = models.CharField(max_length=100)
    author = models.CharField(max_length=100)
    cover = models.CharField(
        max_length=4, choices=CoverType.choices, default=CoverType.HARD
    )
    inventory = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
        help_text="Number of copies available in the library",
    )
    daily_fee = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Daily borrowing fee in USD",
    )

    def __str__(self):
        return f"{self.title} by {self.author}"

    class Meta:
        ordering = ["title", "author"]
        verbose_name = "Book"
        verbose_name_plural = "Books"

        constraints = [
            # Ensure inventory is non-negative
            models.CheckConstraint(
                check=models.Q(inventory__gte=0), name="inventory_non_negative"
            ),
            # Ensure daily fee is positive
            models.CheckConstraint(
                check=models.Q(daily_fee__gt=0), name="daily_fee_positive"
            ),
        ]

    @property
    def is_available(self):
        """Check if the book is available for borrowing"""
        return self.inventory > 0

    def borrow(self):
        """Decrease inventory when book is borrowed"""
        if self.inventory > 0:
            self.inventory -= 1
            self.save()
            return True
        return False

    def return_book(self):
        """Increase inventory when book is returned"""
        self.inventory += 1
        self.save()
