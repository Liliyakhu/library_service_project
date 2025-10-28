import logging
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError

from payments.models import Payment
from payments.stripe_service import StripeService


logger = logging.getLogger(__name__)


def create_payment(
    borrowing, payment_type="payment", request=None, create_session=True
):
    """
    Create a payment for a borrowing with optional Stripe session.

    Args:
        borrowing: Borrowing instance
        payment_type: "payment" (normal fee) or "fine" (late fee)
        request: HTTP request (needed for Stripe session URL generation)
        create_session: Whether to create Stripe checkout session

    Returns:
        Payment instance

    Raises:
        ValueError: If validation fails or payment already exists
        Exception: If Stripe session creation fails

    Examples:
        # Create normal payment with session
        payment = create_payment(borrowing, "payment", request=request)

        # Create fine without session (for batch operations)
        payment = create_payment(borrowing, "fine", create_session=False)
    """
    # Validate payment type
    if payment_type not in ["payment", "fine"]:
        raise ValueError(f"Invalid payment type: {payment_type}")

    # Check if payment already exists
    existing_payment = Payment.objects.filter(
        borrowing=borrowing, type=payment_type, status__in=["pending", "paid"]
    ).first()

    if existing_payment:
        if existing_payment.is_paid:
            raise ValueError(f"A paid {payment_type} already exists for this borrowing")
        # Return existing pending payment
        logger.info(
            f"Returning existing {payment_type} payment {existing_payment.id} "
            f"for borrowing {borrowing.id}"
        )
        return existing_payment

    # Calculate amount based on type
    if payment_type == "payment":
        amount = borrowing.payment_fee
    else:  # fine
        if not borrowing.was_returned_late:
            raise ValueError("Cannot create fine payment for non-overdue borrowing")
        amount = borrowing.fine_fee

    if amount <= 0:
        raise ValueError(f"Payment amount must be greater than 0, got {amount}")

    # Create payment record
    payment = Payment.objects.create(
        borrowing=borrowing,
        money_to_pay=amount,
        type=payment_type,
        status="pending",
    )

    logger.info(
        f"Created {payment_type} payment {payment.id} for borrowing {borrowing.id}: "
        f"${amount}"
    )

    # Create Stripe session if requested
    if create_session:
        if not request:
            # Clean up payment if no request provided
            payment.delete()
            raise ValueError("Request object required to create Stripe session")

        try:
            stripe_result = StripeService.create_checkout_session(
                payment, request=request
            )

            if stripe_result.get("success"):
                payment.session_id = stripe_result["session_id"]
                payment.session_url = stripe_result["session_url"]
                payment.save()
                logger.info(
                    f"Created Stripe session for payment {payment.id}: "
                    f"{stripe_result['session_id']}"
                )
            else:
                payment.delete()
                error_msg = stripe_result.get("error", "Unknown error")
                logger.error(
                    f"Failed to create Stripe session for payment {payment.id}: {error_msg}"
                )
                raise Exception(f"Failed to create Stripe session: {error_msg}")
        except Exception as e:
            if payment.pk:
                payment.delete()
            raise

    return payment


def get_or_create_fine_payment(borrowing, request=None):
    """
    Get existing fine payment or create new one.

    Convenience wrapper for fine payments that may already exist.

    Args:
        borrowing: Borrowing instance
        request: HTTP request for Stripe session

    Returns:
        Payment instance

    Raises:
        ValueError: If borrowing is not overdue
    """
    if not borrowing.was_returned_late:
        raise ValueError("Borrowing is not overdue")

    # Check for existing fine (pending or paid)
    existing_fine = Payment.objects.filter(borrowing=borrowing, type="fine").first()

    if existing_fine:
        logger.info(
            f"Found existing fine payment {existing_fine.id} for borrowing {borrowing.id}"
        )
        return existing_fine

    return create_payment(borrowing, payment_type="fine", request=request)


def get_unpaid_payments_for_user(user):
    """
    Get all unpaid (pending + expired) payments for a user.

    Args:
        user: User instance

    Returns:
        QuerySet of Payment objects
    """
    return Payment.objects.filter(
        borrowing__user=user, status__in=["pending", "expired"]
    ).select_related("borrowing__book", "borrowing__user")


def has_pending_payments(user):
    """
    Check if user has any pending payments.

    Args:
        user: User instance

    Returns:
        bool: True if user has pending payments
    """
    return Payment.objects.filter(borrowing__user=user, status="pending").exists()


def mark_payment_as_paid(payment):
    """
    Mark a payment as paid with proper logging.

    Idempotent - safe to call multiple times.

    Args:
        payment: Payment instance

    Returns:
        Payment instance
    """
    if payment.status == "paid":
        logger.warning(f"Payment {payment.id} is already paid")
        return payment

    old_status = payment.status
    payment.status = "paid"
    payment.save()

    logger.info(
        f"Payment {payment.id} marked as paid (was {old_status}). "
        f"Amount: ${payment.money_to_pay}, Type: {payment.type}"
    )

    return payment
