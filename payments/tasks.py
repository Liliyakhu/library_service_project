import pytz

from celery import shared_task
from django.utils import timezone
from django.db import transaction
from payments.models import Payment
from payments.stripe_service import StripeService
import logging

logger = logging.getLogger(__name__)


KYIV_TZ = pytz.timezone("Europe/Kyiv")


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_expired_stripe_sessions(self):
    """
    Celery task to check for expired Stripe payment sessions and mark them as expired.

    This task runs every minute and:
    1. Finds all pending payments with session_expires_at <= now
    2. Verifies session status with Stripe
    3. Marks expired sessions as "expired"
    4. Logs the results

    Returns:
        dict: Summary of the task execution
    """
    try:
        now = timezone.now().astimezone(KYIV_TZ)

        # Get all pending payments that should be expired
        potentially_expired_payments = Payment.objects.filter(
            status="pending",
            session_id__isnull=False,
            # session_expires_at__isnull=True,
            session_expires_at__lte=now,
        ).select_related("borrowing__book", "borrowing__user")

        expired_count = 0
        still_valid_count = 0
        error_count = 0
        errors = []

        logger.info(
            f"Task {self.request.id}: Checking {potentially_expired_payments.count()} "
            f"potentially expired payment sessions"
        )

        for payment in potentially_expired_payments:
            try:
                with transaction.atomic():
                    # Double-check with Stripe to be sure
                    session = StripeService.retrieve_checkout_session(
                        payment.session_id
                    )

                    if not session:
                        # If we can't retrieve session from Stripe, consider it expired
                        payment.expire_session()
                        expired_count += 1
                        logger.info(
                            f"Task {self.request.id}: Expired payment {payment.id} "
                            f"(could not retrieve from Stripe)"
                        )
                        continue

                    # Check Stripe session status
                    if session.status == "expired":
                        payment.expire_session()
                        expired_count += 1
                        logger.info(
                            f"Task {self.request.id}: Expired payment {payment.id} "
                            f"(confirmed by Stripe)"
                        )
                    elif session.payment_status == "paid":
                        # Session was paid but webhook might have failed
                        payment.status = "paid"
                        payment.save()
                        still_valid_count += 1
                        logger.info(
                            f"Task {self.request.id}: Payment {payment.id} was actually paid, "
                            f"updated status"
                        )
                    elif session.status == "open":
                        # Session is still open, extend expiration time
                        # Stripe sessions can sometimes be extended beyond 24h
                        payment.session_expires_at = now + timezone.timedelta(hours=1)
                        payment.save()
                        still_valid_count += 1
                        logger.info(
                            f"Task {self.request.id}: Payment {payment.id} session still open, "
                            f"extended expiration"
                        )
                    else:
                        # Unknown status, mark as expired to be safe
                        payment.expire_session()
                        expired_count += 1
                        logger.warning(
                            f"Task {self.request.id}: Payment {payment.id} has unknown "
                            f"Stripe status '{session.status}', marked as expired"
                        )

            except Exception as e:
                error_count += 1
                error_msg = f"Error processing payment {payment.id}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"Task {self.request.id}: {error_msg}")

        # Log summary
        total_processed = expired_count + still_valid_count + error_count
        logger.info(
            f"Task {self.request.id}: Processed {total_processed} payments. "
            f"Expired: {expired_count}, Still valid: {still_valid_count}, "
            f"Errors: {error_count}"
        )

        return {
            "task_id": self.request.id,
            "status": "completed",
            "total_checked": potentially_expired_payments.count(),
            "expired_count": expired_count,
            "still_valid_count": still_valid_count,
            "error_count": error_count,
            "errors": errors,
            "timestamp": now.isoformat(),
        }

    except Exception as exc:
        logger.error(
            f"Task {self.request.id}: Unexpected error in check_expired_stripe_sessions: {str(exc)}"
        )
        # Retry the task up to 3 times
        raise self.retry(exc=exc, countdown=60)


@shared_task
def expire_payment_session(payment_id):
    """
    Mark a specific payment session as expired.
    This can be used for individual expiration or testing.

    Args:
        payment_id (int): ID of the payment to expire

    Returns:
        dict: Result of the expiration attempt
    """
    try:
        payment = Payment.objects.get(id=payment_id)

        if payment.status == "paid":
            return {
                "payment_id": payment_id,
                "status": "skipped",
                "reason": "Payment already completed",
            }

        if payment.status == "expired":
            return {
                "payment_id": payment_id,
                "status": "skipped",
                "reason": "Payment already expired",
            }

        # Check with Stripe first
        if payment.session_id:
            session = StripeService.retrieve_checkout_session(payment.session_id)
            if session and session.payment_status == "paid":
                payment.status = "paid"
                payment.save()
                return {
                    "payment_id": payment_id,
                    "status": "updated_to_paid",
                    "reason": "Session was actually paid",
                }

        # Expire the payment
        payment.expire_session()

        return {
            "payment_id": payment_id,
            "status": "expired",
            "message": "Payment session marked as expired",
        }

    except Payment.DoesNotExist:
        return {
            "payment_id": payment_id,
            "status": "error",
            "message": "Payment not found",
        }
    except Exception as e:
        logger.error(f"Error expiring payment {payment_id}: {str(e)}")
        return {"payment_id": payment_id, "status": "error", "message": str(e)}


@shared_task
def cleanup_old_expired_payments():
    """
    Clean up old expired payments (older than 30 days).
    This helps keep the database clean.

    Returns:
        dict: Summary of cleanup operation
    """
    try:
        cutoff_date = timezone.now().astimezone(KYIV_TZ) - timezone.timedelta(days=30)

        # Delete expired payments older than 30 days
        expired_payments = Payment.objects.filter(
            status="expired", created_at__lt=cutoff_date
        )

        count = expired_payments.count()
        expired_payments.delete()

        logger.info(f"Cleaned up {count} old expired payments")

        return {
            "status": "completed",
            "deleted_count": count,
            "cutoff_date": cutoff_date.isoformat(),
            "timestamp": timezone.now().astimezone(KYIV_TZ).isoformat(),
        }

    except Exception as e:
        logger.error(f"Error cleaning up expired payments: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "timestamp": timezone.now().astimezone(KYIV_TZ).isoformat(),
        }
