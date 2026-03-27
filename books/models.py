from django.core.validators import MinValueValidator
from django.db import models, transaction
from decimal import Decimal


class Book(models.Model):
    title = models.CharField(max_length=100)
    author = models.CharField(max_length=100)
    cover = models.CharField(
        max_length=4, choices=[("hard", "Hard"), ("soft", "Soft")], default="hard"
    )
    inventory = models.PositiveIntegerField(default=0)
    daily_fee = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))]
    )

    class Meta:
        ordering = ["title", "author"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(inventory__gte=0), name="positive_inventory"
            ),
            models.CheckConstraint(
                check=models.Q(daily_fee__gt=0), name="positive_fee"
            ),
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"

    @property
    def is_available(self):
        return self.inventory > 0

    @transaction.atomic
    def borrow(self):
        """Atomically borrow book - prevents race conditions"""
        updated = Book.objects.filter(pk=self.pk, inventory__gt=0).update(
            inventory=models.F("inventory") - 1
        )
        if updated:
            self.refresh_from_db()
            return True
        return False

    @transaction.atomic
    def return_book(self):
        """Atomically return book"""
        Book.objects.filter(pk=self.pk).update(inventory=models.F("inventory") + 1)
        self.refresh_from_db()
