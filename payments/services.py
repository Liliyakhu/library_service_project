from payments.models import Payment
from payments.stripe_service import StripeService


def create_payment_for_borrowing(borrowing, request=None):
    """
    Create a Payment + Stripe Checkout Session for a borrowing.
    """
    # 1. Create payment (pending)
    payment = Payment.objects.create(
        borrowing=borrowing,
        money_to_pay=borrowing.total_fee,
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
