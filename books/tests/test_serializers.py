from decimal import Decimal
from django.test import TestCase
from books.models import Book
from books.serializers import BookSerializer


class BookSerializerTestCase(TestCase):
    def setUp(self):
        Book.objects.all().delete()

        self.book = Book.objects.create(
            title="Test Book",
            author="John Doe",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("2.50"),
        )

    def test_serialize_book(self):
        """Serializing a Book instance should return correct data"""
        serializer = BookSerializer(self.book)
        data = serializer.data
        self.assertEqual(data["id"], self.book.id)
        self.assertEqual(data["title"], "Test Book")
        self.assertEqual(data["author"], "John Doe")
        self.assertEqual(data["cover"], "hard")
        self.assertEqual(data["inventory"], 5)
        self.assertEqual(Decimal(data["daily_fee"]), Decimal("2.50"))

    def test_deserialize_valid_data(self):
        """Serializer should validate correct data"""
        data = {
            "title": "New Book",
            "author": "Alice",
            "cover": "soft",
            "inventory": 3,
            "daily_fee": "1.25",
        }
        serializer = BookSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        book = serializer.save()
        self.assertEqual(book.title, "New Book")
        self.assertEqual(book.author, "Alice")
        self.assertEqual(book.cover, "soft")
        self.assertEqual(book.inventory, 3)
        self.assertEqual(book.daily_fee, Decimal("1.25"))

    def test_deserialize_invalid_data_missing_fields(self):
        """Missing required fields should fail validation"""
        data = {"title": "Incomplete Book"}
        serializer = BookSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("author", serializer.errors)
        self.assertIn("daily_fee", serializer.errors)

    def test_deserialize_invalid_data_negative_inventory(self):
        """Inventory must be >= 0"""
        data = {
            "title": "Invalid Inventory",
            "author": "Bob",
            "cover": "hard",
            "inventory": -5,
            "daily_fee": "1.50",
        }
        serializer = BookSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("inventory", serializer.errors)

    def test_deserialize_invalid_data_negative_fee(self):
        """daily_fee must be > 0"""
        data = {
            "title": "Invalid Fee",
            "author": "Bob",
            "cover": "soft",
            "inventory": 3,
            "daily_fee": "0.00",
        }
        serializer = BookSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn("daily_fee", serializer.errors)

    def test_read_only_id_field(self):
        """ID field should be read-only"""
        data = {
            "id": 999,
            "title": "ReadOnly Test",
            "author": "Test Author",
            "cover": "hard",
            "inventory": 1,
            "daily_fee": "1.00",
        }
        serializer = BookSerializer(data=data)
        self.assertTrue(serializer.is_valid())
        book = serializer.save()
        self.assertNotEqual(book.id, 999)  # ID is automatically assigned by DB
