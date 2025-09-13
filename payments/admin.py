from django.contrib import admin
from payments.models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "borrowing",
        "status",
        "type",
        "money_to_pay",
        "borrower_email",
        "book_title",
        "created_at",
    ]
    list_filter = ["status", "type", "created_at"]
    search_fields = [
        "borrowing__user__email",
        "borrowing__book__title",
        "borrowing__book__author",
        "session_id",
    ]
    readonly_fields = ["created_at", "money_to_pay"]

    def borrower_email(self, obj):
        return obj.borrowing.user.email

    borrower_email.short_description = "Borrower Email"

    def book_title(self, obj):
        return obj.borrowing.book.title

    book_title.short_description = "Book Title"
