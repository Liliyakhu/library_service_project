from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from payments.models import Payment
from payments.tasks import check_expired_stripe_sessions, expire_payment_session
from payments.stripe_service import StripeService


class Command(BaseCommand):
    help = "Test session expiration functionality"

    def add_arguments(self, parser):
        parser.add_argument(
            "--payment-id",
            type=int,
            help="Test expiration for specific payment ID",
        )
        parser.add_argument(
            "--create-test-payment",
            action="store_true",
            help="Create a test payment with short expiration for testing",
        )
        parser.add_argument(
            "--run-expiration-task",
            action="store_true",
            help="Manually run the expiration check task",
        )
        parser.add_argument(
            "--expire-all-pending",
            action="store_true",
            help="Mark all pending payments as expired (for testing only)",
        )
        parser.add_argument(
            "--list-expiring-soon",
            type=int,
            default=60,
            help="List payments expiring within N minutes (default: 60)",
        )

    def handle(self, *args, **options):
        if options["payment_id"]:
            self.test_specific_payment(options["payment_id"])

        elif options["create_test_payment"]:
            self.create_test_payment()

        elif options["run_expiration_task"]:
            self.run_expiration_task()

        elif options["expire_all_pending"]:
            if self.confirm_action("Mark ALL pending payments as expired"):
                self.expire_all_pending()

        else:
            # Default: list payments expiring soon
            self.list_expiring_soon(options["list_expiring_soon"])

    def test_specific_payment(self, payment_id):
        """Test expiration for a specific payment"""
        try:
            payment = Payment.objects.get(id=payment_id)

            self.stdout.write(f"\n=== Testing Payment {payment_id} ===")
            self.stdout.write(f"Status: {payment.status}")
            self.stdout.write(f"Type: {payment.type}")
            self.stdout.write(f"Amount: ${payment.money_to_pay}")
            self.stdout.write(f"Created: {payment.created_at}")
            self.stdout.write(f"Expires: {payment.session_expires_at}")
            self.stdout.write(f"Session ID: {payment.session_id}")
            self.stdout.write(f"Is Expired: {payment.is_expired}")
            self.stdout.write(f"Is Renewable: {payment.is_renewable}")

            if payment.session_id:
                self.stdout.write("\n--- Checking with Stripe ---")
                session_status = StripeService.get_session_status(payment.session_id)
                if session_status:
                    self.stdout.write(f"Stripe Status: {session_status['status']}")
                    self.stdout.write(
                        f"Payment Status: {session_status['payment_status']}"
                    )
                    self.stdout.write(f"Stripe Expires: {session_status['expires_at']}")
                else:
                    self.stdout.write("Could not retrieve from Stripe")

            # Test the expiration task for this payment
            self.stdout.write("\n--- Running Expiration Task ---")
            result = expire_payment_session.delay(payment_id)
            self.stdout.write(f"Task Result: {result.get()}")

            # Refresh and show updated status
            payment.refresh_from_db()
            self.stdout.write(f"Updated Status: {payment.status}")

        except Payment.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Payment {payment_id} not found"))

    def create_test_payment(self):
        """Create a test payment that will expire soon"""
        self.stdout.write("\n=== Creating Test Payment ===")

        # Find a borrowing to use (create one if needed)
        from borrowings.models import Borrowing
        from books.models import Book
        from django.contrib.auth import get_user_model

        User = get_user_model()

        # Get or create test user
        user, created = User.objects.get_or_create(
            email="test@example.com",
            defaults={
                "first_name": "Test",
                "last_name": "User",
                "password": "testpassword123",
            },
        )

        # Get or create test book
        book, created = Book.objects.get_or_create(
            title="Test Book for Payment Expiration",
            defaults={
                "author": "Test Author",
                "cover": "HARD",
                "inventory": 5,
                "daily_fee": 1.50,
            },
        )

        # Create test borrowing
        borrowing = Borrowing.objects.create(
            user=user,
            book=book,
            borrow_date=timezone.now().date(),
            expected_return_date=timezone.now().date() + timezone.timedelta(days=7),
        )

        # Create payment with short expiration (1 minute for testing)
        payment = Payment.objects.create(
            borrowing=borrowing,
            type="payment",
            money_to_pay=10.00,
            session_id="test_session_" + str(timezone.now().timestamp()),
            session_url="https://checkout.stripe.com/test",
            session_expires_at=timezone.now() + timezone.timedelta(minutes=1),
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created test payment {payment.id} that will expire in 1 minute"
            )
        )
        self.stdout.write(f"Payment expires at: {payment.session_expires_at}")

    def run_expiration_task(self):
        """Manually run the expiration check task"""
        self.stdout.write("\n=== Running Expiration Check Task ===")

        result = check_expired_stripe_sessions.delay()
        task_result = result.get()

        self.stdout.write("Task completed with result:")
        for key, value in task_result.items():
            self.stdout.write(f"  {key}: {value}")

    def expire_all_pending(self):
        """Mark all pending payments as expired (testing only)"""
        self.stdout.write("\n=== Expiring All Pending Payments ===")

        pending_payments = Payment.objects.filter(status="pending")
        count = pending_payments.count()

        with transaction.atomic():
            updated = pending_payments.update(status="expired")

        self.stdout.write(
            self.style.WARNING(
                f"Marked {updated} payments as expired (was {count} pending)"
            )
        )

    def list_expiring_soon(self, minutes):
        """List payments expiring within specified minutes"""
        cutoff_time = timezone.now() + timezone.timedelta(minutes=minutes)

        expiring_payments = Payment.objects.filter(
            status="pending",
            session_expires_at__lte=cutoff_time,
            session_expires_at__isnull=False,
        ).select_related("borrowing__book", "borrowing__user")

        self.stdout.write(f"\n=== Payments Expiring Within {minutes} Minutes ===")
        self.stdout.write(f"Found {expiring_payments.count()} payments")

        for payment in expiring_payments:
            time_left = payment.session_expires_at - timezone.now()
            minutes_left = int(time_left.total_seconds() / 60)

            self.stdout.write(
                f"Payment {payment.id}: ${payment.money_to_pay} "
                f"({payment.borrowing.book.title}) - "
                f"expires in {minutes_left} minutes"
            )

        # Also show already expired
        expired_payments = Payment.objects.filter(
            status="pending",
            session_expires_at__lt=timezone.now(),
            session_expires_at__isnull=False,
        ).count()

        if expired_payments > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\nAlso found {expired_payments} payments that should already be expired"
                )
            )

    def confirm_action(self, action):
        """Confirm dangerous actions"""
        response = input(f"Are you sure you want to {action}? (yes/no): ")
        return response.lower() == "yes"
