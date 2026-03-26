import json
import stripe
import logging

from django.conf import settings
from django.utils import timezone
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from payments.models import Payment
from payments.serializers import (
    PaymentSerializer,
    PaymentCreateSerializer,
    PaymentDetailSerializer,
)
from payments.permissions import IsOwnerOrStaffForPayments
from payments.stripe_service import StripeService
from users.authentication import AuthorizeHeaderJWTAuthentication

logger = logging.getLogger(__name__)


class PaymentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing payments"""

    authentication_classes = [AuthorizeHeaderJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrStaffForPayments]

    def get_queryset(self):
        """Filter payments based on user permissions"""
        user = self.request.user

        if user.is_staff:
            # Staff can see all payments
            queryset = Payment.objects.select_related(
                "borrowing__book", "borrowing__user"
            ).all()
        else:
            # Regular users can only see their own payments
            queryset = Payment.objects.select_related(
                "borrowing__book", "borrowing__user"
            ).filter(borrowing__user=user)

        # Optional filtering by status
        status_filter = self.request.query_params.get("status")
        if status_filter in ["pending", "paid"]:
            queryset = queryset.filter(status=status_filter)

        return queryset.order_by("-created_at")

    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == "create":
            return PaymentCreateSerializer
        elif self.action in ["retrieve"]:
            return PaymentDetailSerializer
        return PaymentSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Create a new payment and Stripe checkout session"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create the payment object
        payment = serializer.save()

        # Create Stripe checkout session
        stripe_result = StripeService.create_checkout_session(payment)

        if stripe_result["success"]:
            # Update payment with Stripe session info
            payment.session_id = stripe_result["session_id"]
            payment.session_url = stripe_result["session_url"]
            payment.save()

            # Return payment details
            response_serializer = PaymentDetailSerializer(payment)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        else:
            # Delete payment if Stripe session creation failed
            payment.delete()
            return Response(
                {
                    "error": f'Failed to create payment session: {stripe_result.get("error", "Unknown error")}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def update(self, request, *args, **kwargs):
        """Prevent direct payment updates - should be handled via webhooks or specific actions"""
        return Response(
            {
                "error": "Direct payment updates are not allowed. Use payment completion endpoints."
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def destroy(self, request, *args, **kwargs):
        """Only allow deletion of pending payments"""
        payment = self.get_object()

        if payment.status == "paid":
            return Response(
                {"error": "Cannot delete completed payments."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def check_session(self, request, pk=None):
        """Check the status of a Stripe payment session"""
        payment = self.get_object()

        if not payment.session_id:
            return Response(
                {"error": "No Stripe session found for this payment"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check session status with Stripe
        session = StripeService.retrieve_checkout_session(payment.session_id)

        if not session:
            return Response(
                {"error": "Could not retrieve session from Stripe"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Update payment status if paid
        if session.payment_status == "paid" and payment.status == "pending":
            payment.status = "paid"
            payment.save()

        return Response(
            {
                "payment_id": payment.id,
                "payment_status": payment.status,
                "stripe_session_status": session.payment_status,
                "session_url": payment.session_url,
            }
        )

    @action(detail=True, methods=["post"])
    def mark_paid(self, request, pk=None):
        """Manually mark a payment as paid (staff only)"""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can manually mark payments as paid"},
                status=status.HTTP_403_FORBIDDEN,
            )

        payment = self.get_object()

        if payment.status == "paid":
            return Response(
                {"error": "Payment is already marked as paid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment.status = "paid"
        payment.save()

        serializer = PaymentDetailSerializer(payment)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_payments(self, request):
        """Get current user's payments"""
        payments = (
            Payment.objects.select_related("borrowing__book", "borrowing__user")
            .filter(borrowing__user=request.user)
            .order_by("-created_at")
        )

        serializer = PaymentSerializer(payments, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"])
    def create_test_sessions(self, request):
        """Create test Stripe sessions (development only)"""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can create test sessions"},
                status=status.HTTP_403_FORBIDDEN,
            )

        test_sessions = StripeService.create_test_sessions()

        if test_sessions:
            return Response(
                {
                    "message": "Test sessions created successfully",
                    "sessions": test_sessions,
                }
            )
        else:
            return Response(
                {"error": "Failed to create test sessions"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["post"])
    def sync_with_stripe(self, request):
        """Check all pending payments against Stripe and update statuses"""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can sync payment statuses"},
                status=status.HTTP_403_FORBIDDEN,
            )

        pending_payments = Payment.objects.filter(
            status="pending", session_id__isnull=False
        )

        updated_count = 0
        errors = []

        for payment in pending_payments:
            try:
                session = StripeService.retrieve_checkout_session(payment.session_id)
                if session and session.payment_status == "paid":
                    payment.status = "paid"
                    payment.save()
                    updated_count += 1
            except Exception as e:
                errors.append(f"Payment {payment.id}: {str(e)}")

        return Response(
            {
                "message": f"Updated {updated_count} payments to paid status",
                "updated_count": updated_count,
                "total_checked": pending_payments.count(),
                "errors": errors,
            }
        )

    @action(detail=False, methods=["get"])
    def webhook_events(self, request):
        """Get recent webhook events for debugging (staff only)"""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can view webhook events"},
                status=status.HTTP_403_FORBIDDEN,
            )

        events = StripeService.get_webhook_events()

        return Response(
            {
                "events": [
                    {
                        "id": event.id,
                        "type": event.type,
                        "created": event.created,
                        "data": event.data,
                    }
                    for event in events
                ]
            }
        )

    @action(detail=False, methods=["post"])
    def test_webhook(self, request):
        """Test webhook functionality (development only)"""
        if not request.user.is_staff:
            return Response(
                {"error": "Only staff can test webhooks"},
                status=status.HTTP_403_FORBIDDEN,
            )


# Utility views for handling payment success/cancel
def payment_success(request):
    """Handle successful payment redirect"""
    session_id = request.GET.get("session_id")

    if session_id:
        try:
            payment = Payment.objects.get(session_id=session_id)

            # Verify with Stripe and update status
            if StripeService.is_session_paid(session_id):
                payment.status = "paid"
                payment.save()

                return JsonResponse(
                    {
                        "status": "success",
                        "message": "Payment completed successfully!",
                        "payment_id": payment.id,
                    }
                )
            else:
                return JsonResponse(
                    {
                        "status": "pending",
                        "message": "Payment is still processing...",
                        "payment_id": payment.id,
                    }
                )
        except Payment.DoesNotExist:
            return JsonResponse(
                {"status": "error", "message": "Payment not found"}, status=404
            )

    return JsonResponse(
        {"status": "error", "message": "No session ID provided"}, status=400
    )


def payment_cancel(request):
    """Handle cancelled payment redirect"""
    session_id = request.GET.get("session_id")

    return JsonResponse(
        {
            "status": "cancelled",
            "message": "Payment was cancelled",
            "session_id": session_id,
        }
    )
