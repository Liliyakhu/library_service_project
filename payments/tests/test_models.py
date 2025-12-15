import logging
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from django.test import override_settings
from rest_framework.test import APITestCase, APIClient

from borrowings.models import Borrowing
from payments.models import Payment
from books.models import Book
from core.utils.timezone_utils import kyiv_now

User = get_user_model()


class PaymentModelTestCase(APITestCase):
    """Test suite for Payment model"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()

        # Create test user
        self.user = User.objects.create_user(
            email="test@example.com", password="testpass123"
        )

        # Create test book
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        # Create test borrowing
        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create test payment
        self.payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.50"),
        )

    def test_payment_creation(self):
        """Test basic payment creation"""
        payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("5.00"),
        )

        self.assertEqual(payment.borrowing, self.borrowing)
        self.assertEqual(payment.type, "fine")
        self.assertEqual(payment.status, "pending")
        self.assertEqual(payment.money_to_pay, Decimal("5.00"))
        self.assertIsNotNone(payment.created_at)

    def test_payment_str_representation(self):
        """Test string representation of payment"""
        expected = f"Payment {self.payment.id} - Pending - $10.50"
        self.assertEqual(str(self.payment), expected)

    def test_payment_default_values(self):
        """Test default values for payment fields"""
        payment = Payment.objects.create(
            borrowing=self.borrowing, money_to_pay=Decimal("15.00")
        )

        self.assertEqual(payment.status, "pending")
        self.assertEqual(payment.type, "payment")

    def test_positive_money_constraint(self):
        """Test that money_to_pay must be positive"""
        with self.assertRaises(ValidationError):
            payment = Payment(borrowing=self.borrowing, money_to_pay=Decimal("0.00"))
            payment.full_clean()

        with self.assertRaises(ValidationError):
            payment = Payment(borrowing=self.borrowing, money_to_pay=Decimal("-5.00"))
            payment.full_clean()

    def test_session_url_and_id_both_required(self):
        """Test that session_url and session_id must both be present or absent"""
        # Both present - should be valid
        payment = Payment(
            borrowing=self.borrowing,
            money_to_pay=Decimal("10.00"),
            session_url="https://stripe.com/session",
            session_id="sess_123",
        )
        payment.full_clean()  # Should not raise

        # Only session_url - should be invalid
        with self.assertRaises(ValidationError):
            payment = Payment(
                borrowing=self.borrowing,
                money_to_pay=Decimal("10.00"),
                session_url="https://stripe.com/session",
            )
            payment.full_clean()

        # Only session_id - should be invalid
        with self.assertRaises(ValidationError):
            payment = Payment(
                borrowing=self.borrowing,
                money_to_pay=Decimal("10.00"),
                session_id="sess_123",
            )
            payment.full_clean()

    def test_paid_payment_requires_session_data(self):
        """Test that paid payments must have session_url and session_id"""
        with self.assertRaises(ValidationError):
            payment = Payment(
                borrowing=self.borrowing, money_to_pay=Decimal("10.00"), status="paid"
            )
            payment.full_clean()

    def test_unique_session_id_constraint(self):
        """Test that session_id must be unique when not null"""
        Payment.objects.create(
            borrowing=self.borrowing,
            money_to_pay=Decimal("10.00"),
            session_id="sess_unique_123",
            session_url="https://stripe.com/session1",
        )

        with self.assertRaises(ValidationError):
            Payment.objects.create(
                borrowing=self.borrowing,
                money_to_pay=Decimal("15.00"),
                session_id="sess_unique_123",
                session_url="https://stripe.com/session2",
            )

    def test_unique_paid_payment_per_type_constraint(self):
        """Test that only one paid payment per type per borrowing is allowed"""
        # Create first paid payment
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid_1",
            session_url="https://stripe.com/session1",
        )

        # Try to create another paid payment of same type
        with self.assertRaises(ValidationError):
            Payment.objects.create(
                borrowing=self.borrowing,
                type="payment",
                status="paid",
                money_to_pay=Decimal("15.00"),
                session_id="sess_paid_2",
                session_url="https://stripe.com/session2",
            )

        # But different type should work
        fine_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="paid",
            money_to_pay=Decimal("5.00"),
            session_id="sess_paid_fine",
            session_url="https://stripe.com/session3",
        )
        self.assertEqual(fine_payment.type, "fine")

    @override_settings(STRIPE_SESSION_EXPIRY_HOURS=24)
    def test_session_expiration_auto_set(self):
        """Test that session_expires_at is set automatically"""
        with patch("payments.models.kyiv_now") as mock_now:
            fixed_time = kyiv_now()
            mock_now.return_value = fixed_time

            payment = Payment.objects.create(
                borrowing=self.borrowing,
                money_to_pay=Decimal("10.00"),
                session_id="sess_expire_test",
                session_url="https://stripe.com/session",
            )

            expected_expiry = fixed_time + timedelta(hours=24)
            self.assertEqual(payment.session_expires_at, expected_expiry)

    def test_is_paid_property(self):
        """Test is_paid property"""
        self.assertFalse(self.payment.is_paid)

        self.payment.status = "paid"
        self.payment.session_id = "sess_123"
        self.payment.session_url = "https://stripe.com/session"
        self.payment.save()

        self.assertTrue(self.payment.is_paid)

    def test_is_expired_property_with_status(self):
        """Test is_expired property when status is expired"""
        self.payment.status = "expired"
        self.payment.save()

        self.assertTrue(self.payment.is_expired)

    def test_is_expired_property_with_time(self):
        """Test is_expired property based on session_expires_at"""
        # Not expired - future time
        self.payment.session_expires_at = kyiv_now() + timedelta(hours=1)
        self.payment.save()
        self.assertFalse(self.payment.is_expired)

        # Expired - past time
        self.payment.session_expires_at = kyiv_now() - timedelta(hours=1)
        self.payment.save()
        self.assertTrue(self.payment.is_expired)

    def test_is_renewable_property_paid_payment(self):
        """Test that paid payments are not renewable"""
        self.payment.status = "paid"
        self.payment.session_id = "sess_123"
        self.payment.session_url = "https://stripe.com/session"
        self.payment.save()

        self.assertFalse(self.payment.is_renewable)

    def test_is_renewable_property_expired_payment(self):
        """Test that expired payments are renewable"""
        self.payment.status = "expired"
        self.payment.save()

        self.assertTrue(self.payment.is_renewable)

    def test_is_renewable_property_pending_no_session(self):
        """Test that pending payments without session are renewable"""
        self.payment.status = "pending"
        self.payment.session_id = None
        self.payment.session_url = None
        self.payment.save()

        self.assertTrue(self.payment.is_renewable)

    def test_is_renewable_property_pending_expired_session(self):
        """Test that pending payments with expired session are renewable"""
        self.payment.status = "pending"
        self.payment.session_id = "sess_123"
        self.payment.session_url = "https://stripe.com/session"
        self.payment.session_expires_at = kyiv_now() - timedelta(hours=1)
        self.payment.save()

        self.assertTrue(self.payment.is_renewable)

    def test_is_renewable_property_pending_valid_session(self):
        """Test that pending payments with valid session are not renewable"""
        self.payment.status = "pending"
        self.payment.session_id = "sess_123"
        self.payment.session_url = "https://stripe.com/session"
        self.payment.session_expires_at = kyiv_now() + timedelta(hours=1)
        self.payment.save()

        self.assertFalse(self.payment.is_renewable)

    def test_expire_session_method(self):
        """Test expire_session method"""
        self.payment.status = "pending"
        self.payment.save()

        self.payment.expire_session()

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "expired")

    def test_expire_session_only_affects_pending(self):
        """Test that expire_session only works on pending payments"""
        self.payment.status = "paid"
        self.payment.session_id = "sess_123"
        self.payment.session_url = "https://stripe.com/session"
        self.payment.save()

        self.payment.expire_session()

        self.payment.refresh_from_db()
        # Status should remain paid
        self.assertEqual(self.payment.status, "paid")

    @override_settings(STRIPE_SESSION_EXPIRY_HOURS=24)
    def test_renew_session_method(self):
        """Test renew_session method"""
        self.payment.status = "expired"
        self.payment.save()

        with patch("payments.models.kyiv_now") as mock_now:
            fixed_time = kyiv_now()
            mock_now.return_value = fixed_time

            self.payment.renew_session(
                new_session_id="sess_renewed",
                new_session_url="https://stripe.com/renewed",
            )

            self.payment.refresh_from_db()
            self.assertEqual(self.payment.session_id, "sess_renewed")
            self.assertEqual(self.payment.session_url, "https://stripe.com/renewed")
            self.assertEqual(self.payment.status, "pending")
            expected_expiry = fixed_time + timedelta(hours=24)
            self.assertEqual(self.payment.session_expires_at, expected_expiry)

    def test_renew_session_non_renewable_payment(self):
        """Test that renew_session raises error for non-renewable payments"""
        self.payment.status = "paid"
        self.payment.session_id = "sess_123"
        self.payment.session_url = "https://stripe.com/session"
        self.payment.save()

        with self.assertRaises(ValidationError):
            self.payment.renew_session(
                new_session_id="sess_new", new_session_url="https://stripe.com/new"
            )

    def test_payment_ordering(self):
        """Test that payments are ordered by created_at descending"""
        payment1 = Payment.objects.create(
            borrowing=self.borrowing, money_to_pay=Decimal("5.00"), type="fine"
        )

        payment2 = Payment.objects.create(
            borrowing=self.borrowing, money_to_pay=Decimal("10.00"), type="payment"
        )

        payments = Payment.objects.all()
        self.assertEqual(payments[0], payment2)
        self.assertEqual(payments[1], payment1)

    def test_payment_related_name(self):
        """Test that payments can be accessed from borrowing"""
        payment1 = Payment.objects.create(
            borrowing=self.borrowing, money_to_pay=Decimal("5.00")
        )

        payment2 = Payment.objects.create(
            borrowing=self.borrowing, money_to_pay=Decimal("10.00")
        )

        borrowing_payments = self.borrowing.payments.all()
        self.assertEqual(borrowing_payments.count(), 3)  # Including self.payment
        self.assertIn(payment1, borrowing_payments)
        self.assertIn(payment2, borrowing_payments)

    def test_payment_cascade_delete(self):
        """Test that payment is deleted when borrowing is deleted"""
        payment_id = self.payment.id

        self.borrowing.delete()

        with self.assertRaises(Payment.DoesNotExist):
            Payment.objects.get(id=payment_id)

    def test_multiple_pending_payments_same_type(self):
        """Test that multiple pending payments of same type are allowed"""
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        payment2 = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("15.00"),
        )

        self.assertEqual(payment2.type, "payment")
        self.assertEqual(payment2.status, "pending")

    def tearDown(self):
        """Clean up test data"""
        Payment.objects.all().delete()
        Borrowing.objects.all().delete()
        Book.objects.all().delete()
        User.objects.all().delete()
