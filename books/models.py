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
        max_length=20, choices=CoverType.choices, default=CoverType.HARD
    )
    inventory = models.PositiveSmallIntegerField(default=0)
    daily_fee = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0.0), MaxValueValidator(999.99)],
    )

    def __str__(self):
        return f"{self.title} by {self.author}"

    class Meta:
        ordering = ["title"]
