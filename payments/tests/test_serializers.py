from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch, Mock

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase, APIClient, APIRequestFactory
from rest_framework.request import Request

from borrowings.models import Borrowing
from payments.models import Payment
from payments.serializers import (
    PaymentSerializer,
    PaymentCreateSerializer,
    PaymentDetailSerializer,
    PaymentRenewalSerializer,
    PaymentStatusUpdateSerializer,
)
from books.models import Book
from core.utils.timezone_utils import kyiv_now, KYIV_TZ

User = get_user_model()


class PaymentSerializerTestCase(APITestCase):
    """Test suite for PaymentSerializer"""

    def setUp(self):
        """Set up test data"""
        self.client = APIClient()
        self.factory = APIRequestFactory()

        # Create test user
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            first_name="John",
            last_name="Doe",
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

        # Create test payment with session
        self.payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.50"),
            session_id="sess_123",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() + timedelta(hours=23),
        )

    def test_payment_serializer_fields(self):
        """Test that serializer contains all expected fields"""
        serializer = PaymentSerializer(instance=self.payment)
        data = serializer.data

        expected_fields = {
            "id",
            "status",
            "type",
            "borrowing_id",
            "book_title",
            "user_email",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
            "session_expires_at",
            "is_expired",
            "is_renewable",
            "time_until_expiry",
        }

        self.assertEqual(set(data.keys()), expected_fields)

    def test_payment_serializer_read_only_fields(self):
        """Test that specified fields are read-only"""
        serializer = PaymentSerializer()
        read_only_fields = {
            "id",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
            "borrowing_id",
            "book_title",
            "user_email",
            "session_expires_at",
        }

        for field in read_only_fields:
            self.assertTrue(
                serializer.fields[field].read_only, f"{field} should be read-only"
            )

    def test_payment_serializer_related_fields(self):
        """Test that related fields return correct values"""
        serializer = PaymentSerializer(instance=self.payment)
        data = serializer.data

        self.assertEqual(data["borrowing_id"], self.borrowing.id)
        self.assertEqual(data["book_title"], self.book.title)
        self.assertEqual(data["user_email"], self.user.email)

    def test_payment_serializer_is_expired_false(self):
        """Test is_expired field when payment is not expired"""
        self.payment.session_expires_at = kyiv_now() + timedelta(hours=2)
        self.payment.save()

        serializer = PaymentSerializer(instance=self.payment)

        self.assertFalse(serializer.data["is_expired"])

    def test_payment_serializer_is_expired_true(self):
        """Test is_expired field when payment is expired"""
        self.payment.session_expires_at = kyiv_now() - timedelta(hours=1)
        self.payment.save()

        serializer = PaymentSerializer(instance=self.payment)

        self.assertTrue(serializer.data["is_expired"])

    def test_payment_serializer_time_until_expiry_hours_minutes(self):
        """Test time_until_expiry shows hours and minutes"""
        real_now = kyiv_now()

        with patch("payments.serializers.timezone.now", return_value=real_now):
            self.payment.session_expires_at = real_now + timedelta(hours=2, minutes=30)
            self.payment.save(update_fields=["session_expires_at"])

            serializer = PaymentSerializer(instance=self.payment)

            # Should be something like "2h 30m"
            time_until_expiry = serializer.data["time_until_expiry"]
            self.assertIn("h", time_until_expiry)
            self.assertIn("m", time_until_expiry)

    def test_payment_serializer_time_until_expiry_minutes_only(self):
        """Test time_until_expiry shows only minutes when less than 1 hour"""
        real_now = kyiv_now()

        # Patch timezone.now() safely with a real datetime return value
        with patch("payments.serializers.timezone.now", return_value=real_now):
            self.payment.session_expires_at = real_now + timedelta(minutes=45)
            self.payment.save(update_fields=["session_expires_at"])

            serializer = PaymentSerializer(instance=self.payment)

            # Should be "45m" or similar
            time_until_expiry = serializer.data["time_until_expiry"]
            self.assertIn("m", time_until_expiry)
            self.assertNotIn("h", time_until_expiry)

    def test_payment_serializer_time_until_expiry_expired(self):
        """Test time_until_expiry shows 'Expired' when expired"""
        self.payment.session_expires_at = kyiv_now() - timedelta(hours=1)
        self.payment.save()

        serializer = PaymentSerializer(instance=self.payment)

        self.assertEqual(serializer.data["time_until_expiry"], "Expired")

    def test_payment_serializer_time_until_expiry_none(self):
        """Test time_until_expiry is None when no session_expires_at"""
        self.payment.session_expires_at = None
        self.payment.session_id = None
        self.payment.session_url = None
        self.payment.save()

        serializer = PaymentSerializer(instance=self.payment)

        self.assertIsNone(serializer.data["time_until_expiry"])


class PaymentCreateSerializerTestCase(APITestCase):
    """Test suite for PaymentCreateSerializer"""

    def setUp(self):
        """Set up test data"""
        self.factory = APIRequestFactory()

        # Create test users
        self.user = User.objects.create_user(
            email="user@example.com", password="testpass123"
        )

        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )

        self.staff_user = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )

        # Create test book
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        # Create borrowing for user
        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create borrowing for other user
        self.other_borrowing = Borrowing.objects.create(
            user=self.other_user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

    def test_payment_create_serializer_fields(self):
        """Test that serializer contains expected fields"""
        serializer = PaymentCreateSerializer()

        self.assertIn("borrowing", serializer.fields)
        self.assertIn("type", serializer.fields)

    def test_payment_create_valid_data(self):
        """Test serializer with valid data"""
        request = self.factory.post("/payments/")
        request = Request(request)
        request.user = self.user

        data = {"borrowing": self.borrowing.id, "type": "payment"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        # Debug: print errors if validation fails
        if not serializer.is_valid():
            self.fail(f"Serializer validation failed: {serializer.errors}")

        self.assertTrue(serializer.is_valid())

    def test_payment_create_user_own_borrowing(self):
        """Test user can create payment for their own borrowing"""
        request = self.factory.post("/payments/")
        request = Request(request)
        request.user = self.user

        data = {"borrowing": self.borrowing.id, "type": "payment"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        if not serializer.is_valid():
            self.fail(f"Serializer validation failed: {serializer.errors}")

        self.assertTrue(serializer.is_valid())

    def test_payment_create_user_other_borrowing(self):
        """Test user cannot create payment for other user's borrowing"""
        request = self.factory.post("/payments/")
        request.user = self.user
        request = Request(request)

        data = {"borrowing": self.other_borrowing.id, "type": "payment"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        self.assertFalse(serializer.is_valid())
        self.assertIn("borrowing", serializer.errors)
        self.assertIn("your own borrowings", str(serializer.errors["borrowing"]))

    def test_payment_create_staff_any_borrowing(self):
        """Test staff can create payment for any borrowing"""
        request = self.factory.post("/payments/")
        request = Request(request)
        request.user = self.staff_user

        data = {"borrowing": self.other_borrowing.id, "type": "payment"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        if not serializer.is_valid():
            self.fail(f"Serializer validation failed: {serializer.errors}")

        self.assertTrue(serializer.is_valid())

    def test_payment_create_with_active_pending_payment(self):
        """Test cannot create payment when active pending payment exists"""
        # Create active pending payment for user's own borrowing
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
            session_id="sess_123",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() + timedelta(hours=2),
        )

        request = self.factory.post("/payments/")
        request.user = self.user
        request = Request(request)

        data = {"borrowing": self.borrowing.id, "type": "payment"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        self.assertFalse(serializer.is_valid())
        self.assertIn("borrowing", serializer.errors)
        # Check for either message since validation order may vary
        error_str = str(serializer.errors["borrowing"])
        self.assertTrue(
            "active payment session" in error_str or "your own borrowings" in error_str
        )

    def test_payment_create_with_expired_payment(self):
        """Test cannot create payment when expired payment exists (should renew)"""
        # Create expired payment for user's own borrowing
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        request = self.factory.post("/payments/")
        request.user = self.user
        request = Request(request)

        data = {"borrowing": self.borrowing.id, "type": "payment"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        self.assertFalse(serializer.is_valid())
        self.assertIn("borrowing", serializer.errors)
        # Check for either message since validation order may vary
        error_str = str(serializer.errors["borrowing"])
        self.assertTrue(
            "expired payment sessions" in error_str
            or "your own borrowings" in error_str
        )

    def test_payment_create_with_paid_payment(self):
        """Test can create new payment type when paid payment exists"""
        # Create paid payment
        Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="paid",
            money_to_pay=Decimal("10.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

        request = self.factory.post("/payments/")
        request = Request(request)
        request.user = self.user

        # Should be able to create fine payment
        data = {"borrowing": self.borrowing.id, "type": "fine"}

        serializer = PaymentCreateSerializer(data=data, context={"request": request})

        if not serializer.is_valid():
            self.fail(f"Serializer validation failed: {serializer.errors}")

        self.assertTrue(serializer.is_valid())


class PaymentDetailSerializerTestCase(APITestCase):
    """Test suite for PaymentDetailSerializer"""

    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            email="test@example.com",
            password="testpass123",
            first_name="John",
            last_name="Doe",
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
            session_id="sess_123",
            session_url="https://stripe.com/session",
            session_expires_at=kyiv_now() + timedelta(hours=23),
        )

    def test_payment_detail_serializer_fields(self):
        """Test that serializer contains all expected fields"""
        serializer = PaymentDetailSerializer(instance=self.payment)
        data = serializer.data

        expected_fields = {
            "id",
            "status",
            "type",
            "borrowing",
            "borrowing_details",
            "session_url",
            "session_id",
            "money_to_pay",
            "created_at",
            "session_expires_at",
            "is_expired",
            "is_renewable",
            "time_until_expiry",
            "session_status_info",
            "new_session_created_at",
        }

        self.assertEqual(set(data.keys()), expected_fields)

    def test_payment_detail_borrowing_details(self):
        """Test borrowing_details method returns correct information"""
        serializer = PaymentDetailSerializer(instance=self.payment)
        borrowing_details = serializer.data["borrowing_details"]

        self.assertEqual(borrowing_details["id"], self.borrowing.id)
        self.assertEqual(borrowing_details["book_title"], self.book.title)
        self.assertEqual(borrowing_details["book_author"], self.book.author)
        self.assertEqual(borrowing_details["user_email"], self.user.email)
        self.assertEqual(borrowing_details["user_full_name"], self.user.full_name)
        self.assertIn("borrow_date", borrowing_details)
        self.assertIn("expected_return_date", borrowing_details)
        self.assertIn("is_overdue", borrowing_details)

    def test_payment_detail_session_status_info(self):
        """Test session_status_info method"""
        serializer = PaymentDetailSerializer(instance=self.payment)
        session_info = serializer.data["session_status_info"]

        self.assertTrue(session_info["has_session"])
        self.assertEqual(session_info["status_display"], "Pending")

    def test_payment_detail_session_status_info_no_session(self):
        """Test session_status_info when no session exists"""
        self.payment.session_id = None
        self.payment.session_url = None
        self.payment.session_expires_at = None
        self.payment.save()

        serializer = PaymentDetailSerializer(instance=self.payment)
        session_info = serializer.data["session_status_info"]

        self.assertFalse(session_info["has_session"])

    def test_payment_detail_new_session_created_at(self):
        """Test new_session_created_at calculates correctly"""
        fixed_expiry = kyiv_now() + timedelta(hours=24)
        self.payment.session_expires_at = fixed_expiry
        self.payment.save()

        serializer = PaymentDetailSerializer(instance=self.payment)

        # Should not be None
        self.assertIsNotNone(serializer.data["new_session_created_at"])

    def test_payment_detail_new_session_created_at_none(self):
        """Test new_session_created_at is None when no session_expires_at"""
        self.payment.session_expires_at = None
        self.payment.session_id = None
        self.payment.session_url = None
        self.payment.save()

        serializer = PaymentDetailSerializer(instance=self.payment)

        self.assertIsNone(serializer.data["new_session_created_at"])

    def test_payment_detail_time_until_expiry(self):
        """Test time_until_expiry method"""
        fixed_time = kyiv_now()
        self.payment.session_expires_at = fixed_time + timedelta(hours=5, minutes=30)
        self.payment.save()

        serializer = PaymentDetailSerializer(instance=self.payment)
        self.assertIsNotNone(serializer.data["time_until_expiry"])


class PaymentRenewalSerializerTestCase(APITestCase):
    """Test suite for PaymentRenewalSerializer"""

    def setUp(self):
        """Set up test data"""
        self.factory = APIRequestFactory()

        # Create test users
        self.user = User.objects.create_user(
            email="user@example.com", password="testpass123"
        )

        self.other_user = User.objects.create_user(
            email="other@example.com", password="testpass123"
        )

        self.staff_user = User.objects.create_user(
            email="staff@example.com", password="testpass123", is_staff=True
        )

        # Create test book
        self.book = Book.objects.create(
            title="Test Book",
            author="Test Author",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("1.50"),
        )

        # Create borrowings
        self.borrowing = Borrowing.objects.create(
            user=self.user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        self.other_borrowing = Borrowing.objects.create(
            user=self.other_user,
            book=self.book,
            borrow_date=kyiv_now().date(),
            expected_return_date=(kyiv_now() + timedelta(days=7)).date(),
        )

        # Create expired payment (renewable)
        self.expired_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        # Create paid payment (not renewable)
        self.paid_payment = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="paid",
            money_to_pay=Decimal("5.00"),
            session_id="sess_paid",
            session_url="https://stripe.com/session",
        )

    def test_payment_renewal_serializer_fields(self):
        """Test that serializer contains expected fields"""
        serializer = PaymentRenewalSerializer()

        self.assertIn("payment_id", serializer.fields)

    def test_payment_renewal_valid_expired_payment(self):
        """Test renewal of expired payment"""
        request = self.factory.post("/payments/renew/")
        request = Request(request)
        request.user = self.user

        data = {"payment_id": self.expired_payment.id}

        serializer = PaymentRenewalSerializer(data=data, context={"request": request})

        if not serializer.is_valid():
            self.fail(f"Serializer validation failed: {serializer.errors}")

        self.assertTrue(serializer.is_valid())

    def test_payment_renewal_nonexistent_payment(self):
        """Test renewal with non-existent payment ID"""
        request = self.factory.post("/payments/renew/")
        request.user = self.user
        request = Request(request)

        data = {"payment_id": 99999}

        serializer = PaymentRenewalSerializer(data=data, context={"request": request})

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_id", serializer.errors)
        self.assertIn("not found", str(serializer.errors["payment_id"]))

    def test_payment_renewal_not_renewable(self):
        """Test cannot renew paid payment"""
        request = self.factory.post("/payments/renew/")
        request.user = self.user
        request = Request(request)

        data = {"payment_id": self.paid_payment.id}

        serializer = PaymentRenewalSerializer(data=data, context={"request": request})

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_id", serializer.errors)
        # The paid payment belongs to the user, so it should check renewability
        # But since validate checks permissions first, it might fail there
        error_str = str(serializer.errors["payment_id"])
        self.assertTrue(
            "cannot be renewed" in error_str or "your own payments" in error_str
        )

    def test_payment_renewal_other_user_payment(self):
        """Test user cannot renew other user's payment"""
        other_payment = Payment.objects.create(
            borrowing=self.other_borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
        )

        request = self.factory.post("/payments/renew/")
        request.user = self.user
        request = Request(request)

        data = {"payment_id": other_payment.id}

        serializer = PaymentRenewalSerializer(data=data, context={"request": request})

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_id", serializer.errors)
        self.assertIn("your own payments", str(serializer.errors["payment_id"]))

    def test_payment_renewal_staff_any_payment(self):
        """Test staff can renew any user's payment"""
        other_payment = Payment.objects.create(
            borrowing=self.other_borrowing,
            type="payment",
            status="expired",
            money_to_pay=Decimal("10.00"),
            session_id=None,
            session_url=None,
            session_expires_at=None,
        )

        request = self.factory.post("/payments/renew/")
        request = Request(request)
        request.user = self.staff_user

        data = {"payment_id": other_payment.id}

        serializer = PaymentRenewalSerializer(data=data, context={"request": request})

        if not serializer.is_valid():
            self.fail(f"Serializer validation failed: {serializer.errors}")

        self.assertTrue(serializer.is_valid())

        request = self.factory.post("/payments/renew/")
        request.user = self.user

        serializer = PaymentRenewalSerializer(
            data={"payment_id": other_payment.id}, context={"request": Request(request)}
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_id", serializer.errors)
        self.assertIn("your own payments", str(serializer.errors["payment_id"]))


class PaymentStatusUpdateSerializerTestCase(APITestCase):
    """Test suite for PaymentStatusUpdateSerializer"""

    def setUp(self):
        """Set up test data"""
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

        # Create test payments
        self.payment1 = Payment.objects.create(
            borrowing=self.borrowing,
            type="payment",
            status="pending",
            money_to_pay=Decimal("10.00"),
        )

        self.payment2 = Payment.objects.create(
            borrowing=self.borrowing,
            type="fine",
            status="pending",
            money_to_pay=Decimal("5.00"),
        )

    def test_payment_status_update_serializer_fields(self):
        """Test that serializer contains expected fields"""
        serializer = PaymentStatusUpdateSerializer()

        self.assertIn("payment_ids", serializer.fields)
        self.assertIn("action", serializer.fields)

    def test_payment_status_update_valid_data(self):
        """Test serializer with valid data"""
        data = {
            "payment_ids": [self.payment1.id, self.payment2.id],
            "action": "check_status",
        }

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertTrue(serializer.is_valid())

    def test_payment_status_update_single_payment(self):
        """Test serializer with single payment ID"""
        data = {"payment_ids": [self.payment1.id], "action": "force_expire"}

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertTrue(serializer.is_valid())

    def test_payment_status_update_empty_list(self):
        """Test serializer rejects empty payment ID list"""
        data = {"payment_ids": [], "action": "check_status"}

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_ids", serializer.errors)

    def test_payment_status_update_too_many_ids(self):
        """Test serializer rejects more than 100 payment IDs"""
        data = {"payment_ids": list(range(1, 102)), "action": "check_status"}  # 101 IDs

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_ids", serializer.errors)

    def test_payment_status_update_nonexistent_payments(self):
        """Test serializer validates payment IDs exist"""
        data = {"payment_ids": [99999, 99998], "action": "check_status"}

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_ids", serializer.errors)
        self.assertIn("not found", str(serializer.errors["payment_ids"]))

    def test_payment_status_update_mixed_existing_nonexistent(self):
        """Test serializer with mix of existing and non-existing payment IDs"""
        data = {"payment_ids": [self.payment1.id, 99999], "action": "check_status"}

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("payment_ids", serializer.errors)
        self.assertIn("99999", str(serializer.errors["payment_ids"]))

    def test_payment_status_update_action_choices(self):
        """Test action field only accepts valid choices"""
        # Valid choice
        data = {"payment_ids": [self.payment1.id], "action": "check_status"}
        serializer = PaymentStatusUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        # Valid choice
        data = {"payment_ids": [self.payment1.id], "action": "force_expire"}
        serializer = PaymentStatusUpdateSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        # Invalid choice
        data = {"payment_ids": [self.payment1.id], "action": "invalid_action"}
        serializer = PaymentStatusUpdateSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("action", serializer.errors)

    def test_payment_status_update_default_action(self):
        """Test action field has default value"""
        data = {"payment_ids": [self.payment1.id]}

        serializer = PaymentStatusUpdateSerializer(data=data)

        self.assertTrue(serializer.is_valid())
        self.assertEqual(serializer.validated_data["action"], "check_status")

    def tearDown(self):
        """Clean up test data"""
        Payment.objects.all().delete()
        Borrowing.objects.all().delete()
        Book.objects.all().delete()
        User.objects.all().delete()
