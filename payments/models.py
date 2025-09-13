from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError

from borrowings.models import Borrowing


class Payment(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
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

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Ensure money_to_pay is positive
            models.CheckConstraint(
                check=models.Q(money_to_pay__gt=0), name="positive_money_to_pay"
            ),
            # Unique session_id when not null
            models.UniqueConstraint(
                fields=["session_id"],
                condition=models.Q(session_id__isnull=False),
                name="unique_session_id",
            ),
        ]

    def clean(self):
        """Custom validation for Payment model"""
        super().clean()

        # Validate that session_url and session_id are both present or both absent
        if bool(self.session_url) != bool(self.session_id):
            raise ValidationError(
                "session_url and session_id must be both provided or both empty"
            )

        # Validate that paid payments have session data
        if self.status == "paid" and (not self.session_url or not self.session_id):
            raise ValidationError("Paid payments must have session_url and session_id")

    def save(self, *args, **kwargs):
        """Override save to set money_to_pay and validate"""
        # Set money_to_pay from borrowing total_fee if not set
        if not self.money_to_pay:
            self.money_to_pay = self.borrowing.total_fee

        # Run validation
        self.clean()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment {self.id} - {self.get_status_display()} - ${self.money_to_pay}"

    @property
    def is_paid(self):
        """Check if payment is completed"""
        return self.status == "paid"

    @property
    def borrower_email(self):
        """Get borrower's email for convenience"""
        return self.borrowing.user.email

    @property
    def book_title(self):
        """Get book title for convenience"""
        return self.borrowing.book.title
