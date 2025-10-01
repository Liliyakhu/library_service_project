import pytz
import logging
import stripe

from django.urls import reverse
from django.utils import timezone


logger = logging.getLogger(__name__)


KYIV_TZ = pytz.timezone("Europe/Kyiv")


class StripeService:
    @staticmethod
    def create_checkout_session(payment, request):
        try:
            amount_cents = int(payment.money_to_pay * 100)

            success_url = (
                request.build_absolute_uri(reverse("payments:payment_success"))
                + "?session_id={CHECKOUT_SESSION_ID}"
            )

            cancel_url = (
                request.build_absolute_uri(reverse("payments:payment_cancel"))
                + "?session_id={CHECKOUT_SESSION_ID}"
            )

            # Customize product name based on payment type
            if payment.type == "fine":
                product_name = (
                    f"Fine for overdue return: {payment.borrowing.book.title}"
                )
                description = (
                    f"Fine payment for {payment.borrowing.days_overdue} days overdue"
                )
            else:
                product_name = f"Borrowing for {payment.borrowing.book.title}"
                description = f"Payment for borrowing book"

            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[
                    {
                        "price_data": {
                            "currency": "usd",
                            "product_data": {
                                "name": product_name,
                                "description": description,
                            },
                            "unit_amount": amount_cents,
                        },
                        "quantity": 1,
                    }
                ],
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    "payment_id": payment.id,
                    "payment_type": payment.type,
                    "borrowing_id": payment.borrowing.id,
                },
                expires_at=int(
                    (
                        timezone.now().astimezone(KYIV_TZ)
                        + timezone.timedelta(hours=24)
                    ).timestamp()
                ),  # Explicit expiration
            )

            return {
                "success": True,
                "session_id": session.id,
                "session_url": session.url,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def renew_checkout_session(payment, request):
        """
        Create a new checkout session for an expired/renewable payment.

        Args:
            payment: Payment object to renew
            request: HTTP request object

        Returns:
            dict: Result with new session data or error
        """
        try:
            # Verify payment can be renewed
            if not payment.is_renewable:
                return {
                    "success": False,
                    "error": "Payment cannot be renewed (must be expired or pending)",
                }

            # Create new session with same details
            stripe_result = StripeService.create_checkout_session(payment, request)

            if stripe_result["success"]:
                # Update payment with new session data
                payment.renew_session(
                    stripe_result["session_id"], stripe_result["session_url"]
                )

                logger.info(
                    f"Successfully renewed session for payment {payment.id}. "
                    f"New session: {stripe_result['session_id']}"
                )

                return {
                    "success": True,
                    "session_id": stripe_result["session_id"],
                    "session_url": stripe_result["session_url"],
                    "payment_id": payment.id,
                    "message": "Payment session renewed successfully",
                }
            else:
                return stripe_result

        except Exception as e:
            logger.error(f"Error renewing session for payment {payment.id}: {e}")
            return {"success": False, "error": str(e)}

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
    def is_session_expired(session_id):
        """
        Check if a Stripe session is expired

        Args:
            session_id: Stripe session ID

        Returns:
            bool: True if expired, False otherwise, None if error
        """
        session = StripeService.retrieve_checkout_session(session_id)
        if session:
            return session.status == "expired"
        return None

    @staticmethod
    def get_session_status(session_id):
        """
        Get detailed status information for a Stripe session

        Args:
            session_id: Stripe session ID

        Returns:
            dict: Session status details or None if error
        """
        session = StripeService.retrieve_checkout_session(session_id)
        if session:
            return {
                "id": session.id,
                "status": session.status,
                "payment_status": session.payment_status,
                "expires_at": session.expires_at,
                "created": session.created,
                "url": session.url,
                "amount_total": session.amount_total,
                "currency": session.currency,
            }
        return None

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
                    expires_at=int(
                        (
                            timezone.now().astimezone(KYIV_TZ)
                            + timezone.timedelta(hours=24)
                        ).timestamp()
                    ),
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

    @staticmethod
    def expire_session(session_id):
        """
        Manually expire a Stripe session (for testing)

        Args:
            session_id: Stripe session ID

        Returns:
            dict: Result of expiration attempt
        """
        try:
            # Note: Stripe doesn't allow manually expiring sessions via API
            # This is mainly for documentation/testing purposes
            session = StripeService.retrieve_checkout_session(session_id)

            if not session:
                return {"success": False, "error": "Session not found"}

            if session.status == "expired":
                return {"success": True, "message": "Session already expired"}

            return {
                "success": False,
                "error": "Cannot manually expire Stripe sessions. They expire automatically after 24 hours.",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
