from decimal import Decimal
from django.conf import settings

from payments.models import Payment
from payments.stripe_service import StripeService


def create_payment_for_borrowing(borrowing, request=None):
    """
    Create a Payment + Stripe Checkout Session for a borrowing.
    """
    # 1. Create payment (pending)
    payment = Payment.objects.create(
        borrowing=borrowing,
        money_to_pay=borrowing.payment_fee,
        type="payment",
        status="pending",
    )

    # 2. Create Stripe session
    stripe_result = StripeService.create_checkout_session(payment, request=request)

    if stripe_result.get("success"):
        payment.session_id = stripe_result["session_id"]
        payment.session_url = stripe_result["session_url"]
        payment.save()
        return payment
    else:
        # Cleanup if Stripe session creation failed
        payment.delete()
        raise Exception(
            f"Failed to create Stripe session: {stripe_result.get('error', 'Unknown error')}"
        )


def create_fine_payment_for_borrowing(borrowing, request=None):
    """
    Create a FINE Payment + Stripe Checkout Session for an overdue borrowing.
    """
    if not borrowing.was_returned_late:
        raise ValueError("Cannot create fine payment for non-overdue borrowing")

    # Check if fine payment already exists
    existing_fine = Payment.objects.filter(borrowing=borrowing, type="fine").first()

    if existing_fine:
        return existing_fine

    # Calculate fine amount
    fine_amount = borrowing.fine_fee

    if fine_amount <= 0:
        raise ValueError("Fine amount must be greater than 0")

    # 1. Create fine payment (pending)
    payment = Payment.objects.create(
        borrowing=borrowing,
        money_to_pay=fine_amount,
        type="fine",
        status="pending",
    )

    # 2. Create Stripe session if request is provided
    if request:
        stripe_result = StripeService.create_checkout_session(payment, request=request)

        if stripe_result.get("success"):
            payment.session_id = stripe_result["session_id"]
            payment.session_url = stripe_result["session_url"]
            payment.save()
        else:
            # Cleanup if Stripe session creation failed
            payment.delete()
            raise Exception(
                f"Failed to create Stripe session: {stripe_result.get('error', 'Unknown error')}"
            )

    return payment


def get_or_create_fine_payment(borrowing, request=None):
    """
    Get existing fine payment or create new one for overdue borrowing.
    """
    if not borrowing.is_overdue:
        return None

    # Try to get existing fine payment
    existing_fine = Payment.objects.filter(borrowing=borrowing, type="fine").first()

    if existing_fine:
        return existing_fine

    # Create new fine payment
    return create_fine_payment_for_borrowing(borrowing, request)
