"""
Notification message formatters for Telegram.
"""

from django.utils.html import escape


def format_borrowing_notification(borrowing, payment):
    """
    Format Telegram message for new borrowing.

    Args:
        borrowing: Borrowing instance
        payment: Payment instance

    Returns:
        str: Formatted HTML message for Telegram
    """
    book = borrowing.book
    user = borrowing.user

    return (
        "<b>📚 New Borrowing</b>\n"
        f"👤 <b>User</b>: {escape(user.full_name)} ({escape(user.email)})\n"
        f"📖 <b>Book</b>: {escape(book.title)} — {escape(book.author)}\n"
        f"📅 <b>Borrowed</b>: {borrowing.borrow_date:%Y-%m-%d}\n"
        f"🗓️ <b>Due</b>: {borrowing.expected_return_date:%Y-%m-%d}\n"
        f"💸 <b>Daily fee</b>: ${book.daily_fee}\n"
        f"📦 <b>Inventory left</b>: {book.inventory}\n"
        f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
        f"💳 <b>Payment</b>: ${payment.money_to_pay} — {payment.get_type_display()}\n"
        f"🔗 <a href='{payment.session_url}'>Pay now</a>"
    )


def format_fine_notification(borrowing, fine_payment):
    """
    Format Telegram message for fine payment.

    Args:
        borrowing: Borrowing instance
        fine_payment: Payment instance (fine type)

    Returns:
        str: Formatted HTML message for Telegram
    """
    book = borrowing.book
    user = borrowing.user
    days_overdue = borrowing.days_overdue
    fine_amount = fine_payment.money_to_pay

    return (
        "<b>💸 Fine Payment Required</b>\n"
        f"👤 <b>User</b>: {escape(user.full_name)} ({escape(user.email)})\n"
        f"📖 <b>Book</b>: {escape(book.title)} — {escape(book.author)}\n"
        f"📅 <b>Returned</b>: {borrowing.actual_return_date:%Y-%m-%d}\n"
        f"🗓️ <b>Was due</b>: {borrowing.expected_return_date:%Y-%m-%d}\n"
        f"⏰ <b>Days overdue</b>: {days_overdue}\n"
        f"💰 <b>Fine amount</b>: ${fine_amount}\n"
        f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
        f"🔗 <a href='{fine_payment.session_url}'>Pay Fine</a>"
    )


def format_payment_success_notification(payment):
    """
    Format Telegram message for successful payment.

    Args:
        payment: Payment instance

    Returns:
        str: Formatted HTML message for Telegram
    """
    borrowing = payment.borrowing

    return (
        "✅ <b>Successful Payment</b>\n\n"
        f"💳 <b>Payment ID</b>: {payment.id}\n"
        f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
        f"📋 <b>Type</b>: {payment.get_type_display()}\n"
        f"👤 <b>User</b>: {escape(borrowing.user.email)}\n"
        f"📚 <b>Book</b>: {escape(borrowing.book.title)}\n"
        f"💰 <b>Amount</b>: ${payment.money_to_pay}\n"
        f"📅 <b>Date</b>: {payment.created_at:%Y-%m-%d %H:%M:%S}"
    )


def format_overdue_borrowing_alert(borrowing):
    """
    Format Telegram message for overdue borrowing alert.

    Args:
        borrowing: Borrowing instance

    Returns:
        str: Formatted HTML message for Telegram
    """
    book = borrowing.book
    user = borrowing.user
    days_overdue = borrowing.days_overdue

    return (
        "⚠️ <b>OVERDUE BORROWING ALERT</b>\n"
        f"📚 <b>Book</b>: {escape(book.title)}\n"
        f"✏️ <b>Author</b>: {escape(book.author)}\n"
        f"👤 <b>Borrower</b>: {escape(user.full_name)}\n"
        f"📧 <b>Email</b>: {escape(user.email)}\n"
        f"📅 <b>Borrowed</b>: {borrowing.borrow_date:%Y-%m-%d}\n"
        f"🗓️ <b>Due Date</b>: {borrowing.expected_return_date:%Y-%m-%d}\n"
        f"⏰ <b>Days Overdue</b>: {days_overdue} day{'s' if days_overdue != 1 else ''}\n"
        f"💰 <b>Daily Fee</b>: ${book.daily_fee}\n"
        f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
        f"💸 <b>Current Total Fee</b>: ${borrowing.total_amount_due}"
    )


def format_no_overdue_notification(date, checked_at):
    """
    Format Telegram message for no overdue borrowings.

    Args:
        date: Date checked
        checked_at: Datetime when check was performed

    Returns:
        str: Formatted HTML message for Telegram
    """
    return (
        "🎉 <b>No Overdue Borrowings Today!</b>\n"
        f"📅 <b>Date</b>: {date:%Y-%m-%d}\n"
        f"🕘 <b>Checked at</b>: {checked_at:%H:%M (Kyiv time)}\n"
        "✅ All borrowings are up to date!"
    )


def format_overdue_summary(date, checked_at, overdue_count, successful, failed):
    """
    Format Telegram message for overdue borrowings summary.

    Args:
        date: Date checked
        checked_at: Datetime when check was performed
        overdue_count: Total number of overdue borrowings
        successful: Number of successful notifications
        failed: Number of failed notifications

    Returns:
        str: Formatted HTML message for Telegram
    """
    return (
        "📊 <b>Daily Overdue Report</b>\n"
        f"📅 <b>Date</b>: {date:%Y-%m-%d}\n"
        f"🕘 <b>Report Time</b>: {checked_at:%H:%M (Kyiv time)}\n"
        f"⚠️ <b>Total Overdue</b>: {overdue_count}\n"
        f"✅ <b>Notifications Sent</b>: {successful}\n"
        f"❌ <b>Failed Notifications</b>: {failed}"
    )
