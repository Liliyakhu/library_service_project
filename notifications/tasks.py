import logging
from celery import shared_task
from django.utils.html import escape
from django.core.paginator import Paginator

from borrowings.models import Borrowing
from notifications.telegram import send_telegram_message_with_retry
from core.utils.timezone_utils import kyiv_now, kyiv_today


logger = logging.getLogger(__name__)

# Pagination settings
BATCH_SIZE = 50  # Process borrowings in batches


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_overdue_borrowings(self):
    """
    Celery task to check for overdue borrowings and send Telegram notifications.

    This task:
    1. Filters borrowings that are overdue (expected_return_date <= today and not returned)
    2. Sends a detailed Telegram notification for each overdue borrowing
    3. Sends a summary message if no overdue borrowings are found

    Uses pagination to avoid loading all records into memory.
    Processes borrowings in batches for better performance.

    Args:
        self: Celery task instance (for retry functionality)

    Returns:
        dict: Summary of the task execution
    """
    try:
        today = kyiv_today()

        # Get overdue borrowings
        overdue_borrowings = (
            Borrowing.objects.select_related("book", "user")
            .filter(
                expected_return_date__lte=today,
                actual_return_date__isnull=True,  # Not returned yet
            )
            .order_by("expected_return_date", "user__email")
        )

        overdue_count = overdue_borrowings.count()

        logger.info(
            f"Task {self.request.id}: Checking overdue borrowings for {today}. "
            f"Found {overdue_count} overdue borrowings."
        )

        if overdue_count == 0:
            # No overdue borrowings
            message = (
                "🎉 <b>No Overdue Borrowings Today!</b>\n"
                f"📅 <b>Date</b>: {today:%Y-%m-%d}\n"
                f"🕘 <b>Checked at</b>: {kyiv_now():%H:%M (Kyiv time)}\n"
                "✅ All borrowings are up to date!"
            )

            if not send_telegram_message_with_retry(message):
                logger.warning(
                    f"Task {self.request.id}: Failed to send 'no overdue' notification"
                )
                # Retry the task if Telegram notification fails
                raise self.retry(countdown=60)

            logger.info(
                f"Task {self.request.id}: No overdue borrowings found. "
                f"Sent success notification."
            )

            return {
                "task_id": self.request.id,
                "status": "success",
                "overdue_count": 0,
                "message": "No overdue borrowings found",
                "date": today.isoformat(),
                "timestamp": kyiv_now().isoformat(),
            }

        # Process in batches
        paginator = Paginator(overdue_borrowings, BATCH_SIZE)
        successful_notifications = 0
        failed_notifications = 0
        failed_borrowing_ids = []

        for page_num in paginator.page_range:
            page = paginator.page(page_num)
            logger.info(
                f"Task {self.request.id}: Processing batch {page_num}/{paginator.num_pages}"
            )

            for borrowing in page.object_list:
                try:
                    days_overdue = (today - borrowing.expected_return_date).days

                    message = (
                        "⚠️ <b>OVERDUE BORROWING ALERT</b>\n"
                        f"📚 <b>Book</b>: {escape(borrowing.book.title)}\n"
                        f"✍️ <b>Author</b>: {escape(borrowing.book.author)}\n"
                        f"👤 <b>Borrower</b>: {escape(borrowing.user.full_name)}\n"
                        f"📧 <b>Email</b>: {escape(borrowing.user.email)}\n"
                        f"📅 <b>Borrowed</b>: {borrowing.borrow_date:%Y-%m-%d}\n"
                        f"🗓️ <b>Due Date</b>: {borrowing.expected_return_date:%Y-%m-%d}\n"
                        f"⏰ <b>Days Overdue</b>: {days_overdue} day{'s' if days_overdue != 1 else ''}\n"
                        f"💰 <b>Daily Fee</b>: ${borrowing.book.daily_fee}\n"
                        f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
                        f"💸 <b>Current Total Fee</b>: ${borrowing.total_amount_due}\n"
                        f"🕘 <b>Alert Time</b>: {kyiv_now():%H:%M (Kyiv time)}"
                    )

                    success = send_telegram_message_with_retry(message, max_retries=2)

                    if success:
                        successful_notifications += 1
                        logger.debug(
                            f"Task {self.request.id}: Sent notification for borrowing {borrowing.id}"
                        )
                    else:
                        failed_notifications += 1
                        failed_borrowing_ids.append(borrowing.id)
                        logger.warning(
                            f"Task {self.request.id}: Failed notification for borrowing {borrowing.id}"
                        )

                except Exception as e:
                    failed_notifications += 1
                    failed_borrowing_ids.append(borrowing.id)
                    logger.error(
                        f"Task {self.request.id}: Error processing borrowing {borrowing.id}: {str(e)}"
                    )

            # Send summary message
        summary_message = (
            f"📊 <b>Daily Overdue Report</b>\n"
            f"📅 <b>Date</b>: {today:%Y-%m-%d}\n"
            f"🕘 <b>Report Time</b>: {kyiv_now():%H:%M (Kyiv time)}\n"
            f"⚠️ <b>Total Overdue</b>: {overdue_count}\n"
            f"✅ <b>Notifications Sent</b>: {successful_notifications}\n"
            f"❌ <b>Failed Notifications</b>: {failed_notifications}"
        )

        if failed_borrowing_ids:
            # Limit failed IDs in message to avoid message size limits
            if len(failed_borrowing_ids) <= 10:
                summary_message += f"\n🚫 <b>Failed IDs</b>: {', '.join(map(str, failed_borrowing_ids))}"
            else:
                summary_message += (
                    f"\n🚫 <b>Failed IDs</b>: {', '.join(map(str, failed_borrowing_ids[:10]))} "
                    f"(and {len(failed_borrowing_ids) - 10} more)"
                )

        send_telegram_message_with_retry(summary_message)

        logger.info(
            f"Task {self.request.id}: Overdue check completed. "
            f"{successful_notifications} successful, {failed_notifications} failed notifications."
        )

        # If more than half failed, retry
        if failed_notifications > successful_notifications and overdue_count > 0:
            logger.warning(
                f"Task {self.request.id}: Too many failed notifications, retrying..."
            )
            raise self.retry(countdown=300)

        return {
            "task_id": self.request.id,
            "status": "completed",
            "overdue_count": overdue_count,
            "successful_notifications": successful_notifications,
            "failed_notifications": failed_notifications,
            "failed_borrowing_ids": failed_borrowing_ids[:100],  # Limit return size
            "date": today.isoformat(),
            "timestamp": kyiv_now().isoformat(),
        }

    except Exception as exc:
        logger.error(
            f"Task {self.request.id}: Unexpected error in check_overdue_borrowings: {str(exc)}",
            exc_info=True,
        )
        raise self.retry(exc=exc, countdown=60)


@shared_task
def send_overdue_notification(borrowing_id):
    """
    Send notification for a specific overdue borrowing.

    Args:
        borrowing_id (int): ID of the borrowing to send notification for

    Returns:
        dict: Result of the notification attempt
    """
    try:
        borrowing = Borrowing.objects.select_related("book", "user").get(
            id=borrowing_id
        )

        if borrowing.actual_return_date is not None:
            return {
                "borrowing_id": borrowing_id,
                "status": "skipped",
                "reason": "Book already returned",
            }

        today = kyiv_today()

        if borrowing.expected_return_date > today:
            return {
                "borrowing_id": borrowing_id,
                "status": "skipped",
                "reason": "Not overdue yet",
            }

        days_overdue = (today - borrowing.expected_return_date).days

        message = (
            "⚠️ <b>OVERDUE BORROWING ALERT</b>\n"
            f"📚 <b>Book</b>: {escape(borrowing.book.title)}\n"
            f"✍️ <b>Author</b>: {escape(borrowing.book.author)}\n"
            f"👤 <b>Borrower</b>: {escape(borrowing.user.full_name)}\n"
            f"📧 <b>Email</b>: {escape(borrowing.user.email)}\n"
            f"📅 <b>Borrowed</b>: {borrowing.borrow_date:%Y-%m-%d}\n"
            f"🗓️ <b>Due Date</b>: {borrowing.expected_return_date:%Y-%m-%d}\n"
            f"⏰ <b>Days Overdue</b>: {days_overdue} day{'s' if days_overdue != 1 else ''}\n"
            f"💰 <b>Daily Fee</b>: ${borrowing.book.daily_fee}\n"
            f"🧾 <b>Borrowing ID</b>: {borrowing.id}\n"
            f"💸 <b>Current Total Fee</b>: ${borrowing.total_amount_due}\n"
            f"🕘 <b>Alert Time</b>: {kyiv_now():%H:%M (Kyiv time)}"
        )

        success = send_telegram_message_with_retry(message)

        return {
            "borrowing_id": borrowing_id,
            "status": "success" if success else "failed",
            "message": (
                "Notification sent successfully"
                if success
                else "Failed to send notification"
            ),
        }

    except Borrowing.DoesNotExist:
        return {
            "borrowing_id": borrowing_id,
            "status": "error",
            "message": "Borrowing not found",
        }
    except Exception as e:
        logger.error(
            f"Error sending notification for borrowing {borrowing_id}: {str(e)}",
            exc_info=True,
        )
        return {"borrowing_id": borrowing_id, "status": "error", "message": str(e)}
