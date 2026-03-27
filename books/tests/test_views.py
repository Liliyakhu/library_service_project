from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model

from books.models import Book

User = get_user_model()


class BookViewSetTestCase(APITestCase):

    def setUp(self):

        # Create users
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            password="adminpass",
            is_staff=True,
            is_superuser=False,
            is_active=True,
        )
        self.normal_user = User.objects.create_user(
            email="user@example.com",
            password="userpass",
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )

        # Create a sample book
        self.book = Book.objects.create(
            title="Sample Book",
            author="Author A",
            cover="hard",
            inventory=5,
            daily_fee=Decimal("2.50"),
        )

        # self.assertEqual(Book.objects.count(), 1, "FAIL: setUp created more than 1 book.")
        #
        # self.list_url = reverse("books:books-list")

    # ---------------- READ-ONLY ACCESS TESTS ----------------

    def test_list_books_anonymous(self):
        """Anonymous user can view the list of books."""
        client = APIClient()
        url = reverse("books:books-list")
        response = client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        print(response.data)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["title"], "Sample Book")

    def test_retrieve_book_anonymous(self):
        """Anonymous user can view a single book detail."""
        client = APIClient()
        url = reverse("books:books-detail", args=[self.book.id])
        response = client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["id"], self.book.id)

    # ---------------- ADMIN (WRITE) ACCESS TESTS ----------------

    def test_create_book_admin(self):
        """Admin user can successfully create a new book."""
        client = APIClient()
        url = reverse("books:books-list")
        client.force_authenticate(user=self.admin_user)
        data = {
            "title": "New Book",
            "author": "Author B",
            "cover": "soft",
            "inventory": 3,
            "daily_fee": "1.50",
        }
        response = client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Book.objects.count(), 2)
        self.assertTrue(Book.objects.filter(title="New Book").exists())

    def test_update_book_admin(self):
        """Admin user can successfully update a book via PUT (or PATCH)."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        url = reverse("books:books-detail", args=[self.book.id])

        # Use PATCH for simplicity to only send the fields we want to change
        data = {"title": "Updated Title", "inventory": 10}
        response = client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "Updated Title")
        self.assertEqual(self.book.inventory, 10)

    def test_delete_book_admin(self):
        """Admin user can successfully delete a book."""
        client = APIClient()
        client.force_authenticate(user=self.admin_user)
        url = reverse("books:books-detail", args=[self.book.id])
        response = client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Book.objects.filter(id=self.book.id).exists())

    # ---------------- NON-ADMIN (WRITE DENIAL) TESTS ----------------

    def test_create_book_non_admin_denied(self):
        """Non-admin user is denied creation access (403 FORBIDDEN)."""
        client = APIClient()
        url = reverse("books:books-list")
        client.force_authenticate(user=self.normal_user)
        data = {
            "title": "Forbidden Book",
            "author": "Author C",
            "cover": "soft",
            "inventory": 1,
            "daily_fee": "1.00",
        }
        response = client.post(url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Book.objects.count(), 1)  # Only the sample book exists

    def test_update_book_non_admin_denied(self):
        """Non-admin user is denied update access (403 FORBIDDEN)."""
        client = APIClient()
        client.force_authenticate(user=self.normal_user)
        url = reverse("books:books-detail", args=[self.book.id])
        data = {"title": "Should Not Update"}
        response = client.patch(url, data)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "Sample Book")  # Title must not have changed

    def test_delete_book_non_admin_denied(self):
        """Non-admin user is denied delete access (403 FORBIDDEN)."""
        client = APIClient()
        client.force_authenticate(user=self.normal_user)
        url = reverse("books:books-detail", args=[self.book.id])
        response = client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Book.objects.filter(id=self.book.id).exists())

    def test_unsafe_method_anonymous_denied(self):
        """Anonymous user is denied access to any unsafe method (401 UNAUTHORIZED)."""
        client = APIClient()
        url = reverse("books:books-detail", args=[self.book.id])
        response = client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Book.objects.filter(id=self.book.id).exists())

    # ---------------- VALIDATION & FILTERING TESTS ----------------

    def test_create_book_with_invalid_inventory_denied(self):
        """Ensure model/serializer validation denies non-positive inventory."""
        client = APIClient()
        url = reverse("books:books-list")
        client.force_authenticate(user=self.admin_user)

        # Inventory must be positive
        invalid_data = {
            "title": "Bad Inventory",
            "author": "Author D",
            "cover": "hard",
            "inventory": -1,  # Invalid data
            "daily_fee": "2.00",
        }

        response = client.post(url, invalid_data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("inventory", response.data)
        self.assertEqual(Book.objects.count(), 1)  # Only the sample book should exist
