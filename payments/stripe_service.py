import stripe
from django.conf import settings
from decimal import Decimal, ROUND_HALF_UP
import logging

logger = logging.getLogger(__name__)


class StripeService:
    """Service class to handle Stripe payment operations"""

    @staticmethod
    def create_checkout_session(payment):
        """
        Create a Stripe Checkout Session for a payment

        Args:
            payment: Payment object

        Returns:
            dict: Contains session_id and session_url, or None if error
        """

        try:
            # Convert Decimal amount to cents safely
            amount_decimal = payment.money_to_pay or Decimal("0.00")
            # multiply by 100 and round to nearest cent then cast to int
            amount_cents = int(
                (amount_decimal * Decimal("100")).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )

            # Determine success and cancel URLs
            success_url = (
                f"{settings.PAYMENT_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}"
            )
            cancel_url = (
                f"{settings.PAYMENT_CANCEL_URL}?session_id={{CHECKOUT_SESSION_ID}}"
            )

            # Create the checkout session
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": f"Library Service - {payment.get_type_display()}",
                                "description": f"Book: {payment.borrowing.book.title} by {payment.borrowing.book.author}",
                            },
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=str(payment.id),
                metadata={
                    "payment_id": payment.id,
                    "borrowing_id": payment.borrowing.id,
                    "user_email": payment.borrowing.user.email,
                    "payment_type": payment.type,
                },
                # Expire session in 1 hour
                expires_at=int((payment.created_at.timestamp() + 3600)),
            )

            return {
                "session_id": session.id,
                "session_url": session.url,
                "success": True,
            }

        except stripe.error.StripeError as e:
            logger.error(
                f"Stripe error creating checkout session for payment {payment.id}: {e}"
            )
            return {"error": str(e), "success": False}
        except Exception as e:
            logger.error(
                f"Unexpected error creating checkout session for payment {payment.id}: {e}"
            )
            return {"error": "Failed to create payment session", "success": False}

    @staticmethod
    def retrieve_checkout_session(session_id):
        """
        Retrieve a Stripe Checkout Session

        Args:
            session_id: Stripe session ID

        Returns:
            stripe.checkout.Session object or None if error
        """
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            return session
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving session {session_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving session {session_id}: {e}")
            return None

    @staticmethod
    def is_session_paid(session_id):
        """
        Check if a Stripe session is successfully paid

        Args:
            session_id: Stripe session ID

        Returns:
            bool: True if paid, False otherwise
        """
        session = StripeService.retrieve_checkout_session(session_id)
        if session:
            return session.payment_status == "paid"
        return False

    @staticmethod
    def create_test_sessions():
        """
        Helper method to create test Stripe sessions for development/testing
        This is for testing purposes only - creates sessions without saving to DB

        Returns:
            list: List of session dictionaries with test data
        """
        test_sessions = []

        try:
            # Create a few test sessions with different amounts
            test_amounts = [10.00, 25.50, 5.99]  # In dollars

            for i, amount in enumerate(test_amounts, 1):
                amount_cents = int(amount * 100)

                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price_data": {
                                "currency": "usd",
                                "product_data": {
                                    "name": f"Test Library Payment #{i}",
                                    "description": f"Test payment for development - ${amount}",
                                },
                                "unit_amount": amount_cents,
                            },
                            "quantity": 1,
                        }
                    ],
                    mode="payment",
                    success_url="http://localhost:8000/api/payments/success/?session_id={CHECKOUT_SESSION_ID}",
                    cancel_url="http://localhost:8000/api/payments/cancel/?session_id={CHECKOUT_SESSION_ID}",
                    metadata={
                        "test_payment": True,
                        "amount": str(amount),
                    },
                )

                test_sessions.append(
                    {
                        "session_id": session.id,
                        "session_url": session.url,
                        "amount": amount,
                        "description": f"Test payment #{i}",
                    }
                )

            return test_sessions

        except Exception as e:
            logger.error(f"Error creating test sessions: {e}")
            return []

    @staticmethod
    def verify_webhook_signature(payload, signature, secret):
        """
        Verify Stripe webhook signature

        Args:
            payload: Raw request body
            signature: Stripe signature header
            secret: Webhook secret from Stripe

        Returns:
            dict: Parsed event data or None if invalid
        """
        try:
            event = stripe.Webhook.construct_event(payload, signature, secret)
            return event
        except (ValueError, stripe.error.SignatureVerificationError) as e:
            logger.error(f"Webhook signature verification failed: {e}")
            return None

    @staticmethod
    def get_webhook_events():
        """
        Get list of recent webhook events from Stripe (for debugging)

        Returns:
            list: Recent webhook events
        """
        try:
            events = stripe.Event.list(limit=10)
            return events.data
        except stripe.error.StripeError as e:
            logger.error(f"Error retrieving webhook events: {e}")
            return []
