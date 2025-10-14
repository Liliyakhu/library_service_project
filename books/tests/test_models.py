from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from books.models import Book


class BookModelTestCase(TestCase):
    def setUp(self):

        self.book = Book.objects.create(
            title="Test Book",
            author="John Doe",
            cover="hard",
            inventory=3,
            daily_fee=Decimal("2.50"),
        )

    def test_str_representation(self):
        """__str__ returns 'title by author'"""
        self.assertEqual(str(self.book), "Test Book by John Doe")

    def test_default_ordering(self):
        """Books should be ordered by title, then author"""
        Book.objects.create(
            title="A Book", author="Zed", inventory=1, daily_fee=Decimal("1.00")
        )
        Book.objects.create(
            title="Z Book", author="Adam", inventory=1, daily_fee=Decimal("1.00")
        )
        books = list(Book.objects.all())
        titles = [book.title for book in books]
        self.assertEqual(titles, ["A Book", "Test Book", "Z Book"])

    def test_is_available_true(self):
        """is_available returns True if inventory > 0"""
        self.assertTrue(self.book.is_available)

    def test_is_available_false(self):
        """is_available returns False if inventory == 0"""
        self.book.inventory = 0
        self.book.save()
        self.assertFalse(self.book.is_available)

    def test_borrow_reduces_inventory(self):
        """borrow() decreases inventory by 1 and returns True"""
        old_inventory = self.book.inventory
        success = self.book.borrow()
        self.book.refresh_from_db()
        self.assertTrue(success)
        self.assertEqual(self.book.inventory, old_inventory - 1)

    def test_borrow_fails_when_no_inventory(self):
        """borrow() returns False and does not change inventory if inventory == 0"""
        self.book.inventory = 0
        self.book.save()
        success = self.book.borrow()
        self.book.refresh_from_db()
        self.assertFalse(success)
        self.assertEqual(self.book.inventory, 0)

    def test_return_book_increases_inventory(self):
        """return_book() increases inventory by 1"""
        old_inventory = self.book.inventory
        self.book.return_book()
        self.book.refresh_from_db()
        self.assertEqual(self.book.inventory, old_inventory + 1)

    def test_atomic_borrow_transaction(self):
        """borrow() runs atomically (should not break with concurrent transaction)"""
        with transaction.atomic():
            result = self.book.borrow()
        self.assertTrue(result)

    def test_cannot_create_book_with_negative_inventory(self):
        """Should raise IntegrityError if inventory < 0 (check constraint)"""
        with self.assertRaises(IntegrityError):
            Book.objects.create(
                title="Invalid Book",
                author="Author",
                cover="soft",
                inventory=-1,
                daily_fee=Decimal("1.00"),
            )

    def test_cannot_create_book_with_nonpositive_fee(self):
        """Should raise IntegrityError if daily_fee <= 0 (check constraint)"""
        with self.assertRaises(IntegrityError):
            Book.objects.create(
                title="Invalid Fee Book",
                author="Author",
                cover="soft",
                inventory=1,
                daily_fee=Decimal("0.00"),
            )
