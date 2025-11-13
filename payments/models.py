from decimal import Decimal

from django.db import models

from borrowings.models import Borrowing


# Payment:
# Status: Enum: PENDING | PAID
# Type: Enum: PAYMENT | FINE
# Borrowing id: int
# Session url: Url  # url to stripe payment session
# Session id: str  # id of stripe payment session
# Money to pay: decimal (in $USD)  # calculated borrowing total price


class Payment(models.Model):
    status = models.CharField(
        max_length=7,
        choices=[("pending", "Pending"), ("paid", "Paid")],
        default="pending",
    )
    type = models.CharField(
        max_length=7,
        choices=[("payment", "Payment"), ("fine", "Fine")],
        default="payment",
    )
    borrowing = models.ForeignKey(
        Borrowing, on_delete=models.CASCADE, related_name="payments"
    )
    session_url = models.URLField(max_length=500, unique=True)
    session_id = models.CharField(max_length=255, unique=True)
    money_to_pay = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("0.00")
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.money_to_pay:  # only set once
            self.money_to_pay = self.borrowing.total_fee
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment {self.id} - {self.status} - {self.money_to_pay}$"
