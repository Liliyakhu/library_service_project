# 📚 Library Service API

> A comprehensive Django REST API for managing book borrowings, payments, and user notifications in a modern library system.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Django 5.2](https://img.shields.io/badge/django-5.2-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16-red.svg)](https://www.django-rest-framework.org/)

## 🌟 Features

### Core Functionality
- 📖 **Book Management** - CRUD operations for books with inventory tracking
- 👤 **User Authentication** - JWT-based auth with custom `Authorize` header
- 📅 **Borrowing System** - Track book borrowings with date validation
- 💳 **Payment Integration** - Stripe checkout for borrowing fees and late fines
- 🔔 **Telegram Notifications** - Real-time alerts for borrowings, payments, and overdue books
- ⏰ **Automated Tasks** - Celery-based periodic checks for overdue borrowings

### Advanced Features
- 🔄 **Payment Session Renewal** - Extend expired Stripe checkout sessions
- 💰 **Fine Calculation** - Automatic late return fee computation
- 🔒 **Race Condition Prevention** - Atomic operations for inventory management
- 🌍 **Timezone Handling** - Consistent Kyiv timezone across the system
- 📊 **API Documentation** - Interactive Swagger/ReDoc documentation
- 🐛 **Debug Tools** - Django Debug Toolbar for development

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Stripe Account (for payments)
- Telegram Bot (for notifications)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/Liliyakhu/library_service_project/
cd library_service_project
```

2. **Create environment file**
```bash
cp .env.sample .env
```

3. **Configure `.env` file**
```env
# Django Settings
DEBUG=True
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1

# Database (when using PostgreSQL)
POSTGRES_DB=library_db
POSTGRES_USER=library_user
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=db
POSTGRES_PORT=5432

# Stripe Configuration
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Telegram Notifications
TELEGRAM_NOTIFICATIONS_ENABLED=True
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# Celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Business Logic
FINE_MULTIPLIER=2.0
MAX_BORROWING_DAYS=30
```

4. **Run with Docker Compose**
```bash
docker compose up --build
```

The application will be available at: `http://localhost:8000`

---

## 📖 API Documentation

### Interactive Documentation
- **Swagger UI**: http://localhost:8000/api/doc/swagger/
- **ReDoc**: http://localhost:8000/api/doc/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

### Authentication

This API uses JWT authentication with a **custom header**:

```bash
# Get access token
curl -X POST http://localhost:8000/api/users/token/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "password123"}'

# Use token in requests (note the custom "Authorize" header)
curl -X GET http://localhost:8000/api/books/ \
  -H "Authorize: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Note**: Use `Authorize` header, **not** `Authorization`!

---

## 🔌 API Endpoints

### 👤 Users
| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/users/register/` | Register new user | ❌ |
| POST | `/api/users/token/` | Obtain JWT token | ❌ |
| POST | `/api/users/token/refresh/` | Refresh JWT token | ❌ |
| GET | `/api/users/me/` | Get current user profile | ✅ |
| PATCH | `/api/users/me/` | Update profile | ✅ |

### 📚 Books
| Method | Endpoint | Description | Auth | Permission |
|--------|----------|-------------|------|------------|
| GET | `/api/books/` | List all books | ❌ | Public |
| GET | `/api/books/{id}/` | Get book details | ❌ | Public |
| POST | `/api/books/` | Create book | ✅ | Admin only |
| PUT/PATCH | `/api/books/{id}/` | Update book | ✅ | Admin only |
| DELETE | `/api/books/{id}/` | Delete book | ✅ | Admin only |

**Query Parameters:**
- `?title=<search>` - Filter books by title

### 📅 Borrowings
| Method | Endpoint | Description | Auth | Permission |
|--------|----------|-------------|------|------------|
| GET | `/api/borrowings/` | List borrowings | ✅ | Own/Admin |
| GET | `/api/borrowings/{id}/` | Get borrowing details | ✅ | Owner/Admin |
| POST | `/api/borrowings/` | Create borrowing | ✅ | Authenticated |
| POST | `/api/borrowings/{id}/return_book/` | Return borrowed book | ✅ | Owner/Admin |
| GET | `/api/borrowings/can_borrow/` | Check borrowing eligibility | ✅ | Authenticated |
| PATCH | `/api/borrowings/{id}/` | Update borrowing | ✅ | Admin only |

**Query Parameters:**
- `?is_active=true` - Filter active borrowings
- `?is_active=false` - Filter returned borrowings
- `?user_id=<id>` - Filter by user (admin only)

### 💳 Payments
| Method | Endpoint | Description | Auth | Permission |
|--------|----------|-------------|------|------------|
| GET | `/api/payments/` | List payments | ✅ | Own/Admin |
| GET | `/api/payments/{id}/` | Get payment details | ✅ | Owner/Admin |
| POST | `/api/payments/` | Create payment | ✅ | Authenticated |
| POST | `/api/payments/{id}/renew_session/` | Renew expired session | ✅ | Owner/Admin |
| GET | `/api/payments/{id}/session_status/` | Check Stripe status | ✅ | Owner/Admin |
| GET | `/api/payments/my_payments/` | Get user's payments | ✅ | Authenticated |
| GET | `/api/payments/renewable_payments/` | List renewable payments | ✅ | Authenticated |
| GET | `/api/payments/success/` | Payment success callback | ❌ | Public |
| GET | `/api/payments/cancel/` | Payment cancel callback | ❌ | Public |

**Query Parameters:**
- `?status=pending` - Filter by status (pending/paid/expired)

---

## 🔄 Typical User Flow

### 1. Register and Login
```bash
# Register
curl -X POST http://localhost:8000/api/users/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john@example.com",
    "password": "secure123",
    "first_name": "John",
    "last_name": "Doe"
  }'

# Get token
curl -X POST http://localhost:8000/api/users/token/ \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john@example.com",
    "password": "secure123"
  }'
```

### 2. Browse Books
```bash
curl -X GET http://localhost:8000/api/books/?title=python
```

### 3. Create Borrowing
```bash
curl -X POST http://localhost:8000/api/borrowings/ \
  -H "Authorize: <your-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "book": 1,
    "expected_return_date": "2025-11-15"
  }'
```

**Response includes:**
- Borrowing details
- Automatic payment creation
- Stripe checkout URL

### 4. Complete Payment
- Visit the `session_url` from the response
- Complete Stripe checkout
- Receive Telegram notification

### 5. Return Book
```bash
curl -X POST http://localhost:8000/api/borrowings/1/return_book/ \
  -H "Authorize: <your-token>"
```

**If returned late:**
- Fine payment is automatically created
- Receive Telegram notification with fine details

---

## 💰 Payment System

### Payment Types
- **Payment** - Normal borrowing fee (`daily_fee × borrowing_days`)
- **Fine** - Late return penalty (`daily_fee × days_late × fine_multiplier`)

### Payment Lifecycle
```
pending → paid (successful payment)
   ↓
expired → renewed → pending (session renewal)
```

### Session Management
- Stripe sessions expire after **24 hours**
- Expired sessions can be **renewed** without creating new payments
- Automatic expiration checks via Celery tasks

### Preventing Multiple Borrowings
Users **cannot create new borrowings** if they have:
- Pending payments
- Expired payments that need renewal

**Check eligibility:**
```bash
GET /api/borrowings/can_borrow/
```

---

## 🔔 Telegram Notifications

### Setup Telegram Bot

1. **Create bot with BotFather**
```
/newbot
<bot-name>
<bot-username>
```

2. **Get chat ID**
```bash
# Send message to your bot, then:
curl https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

3. **Update `.env`**
```env
TELEGRAM_NOTIFICATIONS_ENABLED=True
TELEGRAM_BOT_TOKEN=<your-bot-token>
TELEGRAM_CHAT_ID=<your-chat-id>
```

### Notification Types
- 📚 **New Borrowing** - When book is borrowed
- 💸 **Fine Required** - When book returned late
- ✅ **Payment Success** - When payment completed
- ⚠️ **Overdue Alert** - Daily check for overdue books
- 🎉 **No Overdues** - Confirmation when all books returned on time

---

## ⏰ Celery Tasks

### Available Tasks

1. **Check Overdue Borrowings** (`check_overdue_borrowings`)
   - Runs daily to find overdue books
   - Sends Telegram notifications for each overdue borrowing
   - Provides summary report

2. **Check Expired Stripe Sessions** (`check_expired_stripe_sessions`)
   - Runs every minute
   - Marks expired payment sessions as `expired`
   - Verifies session status with Stripe

3. **Cleanup Old Expired Payments** (`cleanup_old_expired_payments`)
   - Runs weekly
   - Deletes expired payments older than 30 days

### Manual Task Execution

```bash
# Check overdue borrowings (synchronous)
python manage.py check_overdue_borrowings

# Check overdue borrowings (async via Celery)
python manage.py check_overdue_borrowings --async

# Test notification for specific borrowing
python manage.py send_overdue_notification <borrowing_id>
```

### Celery Commands

```bash
# Start Celery worker
celery -A library_service worker -l INFO

# Start Celery beat scheduler
celery -A library_service beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler

# Monitor with Flower
celery -A library_service flower --address=0.0.0.0
# Visit: http://localhost:5555
```

---

## 🔧 Development

### Running Tests
```bash
# All tests
pytest

# With coverage
pytest --cov=. --cov-report=term

# Coverage summary only
pytest --cov=. --cov-report=term | grep 'TOTAL'

# Detailed coverage (shows missing lines)
pytest --cov=. --cov-report=term-missing
```

### Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### Create Superuser
```bash
python manage.py createsuperuser
```

### Code Formatting
```bash
black .
```

### Stripe Webhook Testing

```bash
# Forward webhooks to local server
stripe listen --forward-to localhost:8000/api/payments/webhook/

# Test webhook
stripe trigger checkout.session.completed
```

---

## 🐳 Docker Services

| Service | Port | Description |
|---------|------|-------------|
| **library** | 8000 | Main Django application |
| **db** | 5432 | PostgreSQL database |
| **redis** | 6379 | Celery message broker |
| **celery** | - | Celery worker |
| **celery-beat** | - | Celery scheduler |
| **flower** | 5555 | Celery monitoring |
| **stripe-webhook** | - | Stripe CLI webhook forwarder |

### Docker Commands
```bash
# Start all services
docker compose up

# Rebuild and start
docker compose up --build

# Stop all services
docker compose down

# View logs
docker compose logs -f library

# Execute commands in container
docker compose exec library python manage.py shell
```

---

## 🔒 Security Features

- ✅ JWT-based authentication
- ✅ Password hashing
- ✅ CSRF protection for webhooks (csrf_exempt only for Stripe)
- ✅ Stripe webhook signature verification
- ✅ Permission-based access control
- ✅ Input validation with DRF serializers
- ✅ SQL injection prevention (Django ORM)
- ✅ Rate limiting (configurable)

---

## 🎯 Business Logic

### Fine Calculation
```python
fine_amount = days_late × daily_fee × FINE_MULTIPLIER
```
Default `FINE_MULTIPLIER` = 2.0

### Borrowing Constraints
- ✅ Maximum borrowing period: 30 days (configurable)
- ✅ Cannot borrow if pending payments exist
- ✅ Cannot borrow same book twice simultaneously
- ✅ Inventory atomically decremented on borrow
- ✅ Expected return date must be after borrow date

### Inventory Management
```python
# Race condition prevention
Book.objects.filter(pk=self.pk, inventory__gt=0).update(
    inventory=models.F("inventory") - 1
)
```

---

## 🌍 Timezone Handling

All dates/times use **Europe/Kyiv** timezone:

```python
from core.utils.timezone_utils import kyiv_now, kyiv_today

# Get current Kyiv time
now = kyiv_now()

# Get current Kyiv date
today = kyiv_today()
```

---

## 📊 Admin Interface

Access Django admin at: `http://localhost:8000/admin/`

**Features:**
- Manage books, borrowings, payments
- View Celery periodic tasks
- User management
- Database inspection

---

## 🐛 Debugging

### Django Debug Toolbar
Available at: `http://localhost:8000/__debug__/`

### Query Optimization
The project includes `select_related()` and `prefetch_related()` to minimize N+1 queries.

### Logging
Logs are stored in: `logs/library.log`

---

## 📝 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | False | Enable debug mode |
| `SECRET_KEY` | - | Django secret key |
| `ALLOWED_HOSTS` | - | Comma-separated hosts |
| `FINE_MULTIPLIER` | 2.0 | Late return fee multiplier |
| `MAX_BORROWING_DAYS` | 30 | Maximum borrowing period |
| `STRIPE_SESSION_EXPIRY_HOURS` | 24 | Checkout session duration |
| `OLD_PAYMENT_CLEANUP_DAYS` | 30 | Cleanup threshold |

---

## 🚨 Troubleshooting

### Issue: Telegram notifications not working
```bash
# Check environment variables
docker compose exec library python manage.py shell
>>> from django.conf import settings
>>> settings.TELEGRAM_NOTIFICATIONS_ENABLED
>>> settings.TELEGRAM_BOT_TOKEN
>>> settings.TELEGRAM_CHAT_ID

# Test notification
>>> from notifications.telegram import send_telegram_message
>>> send_telegram_message("Test message")
```

### Issue: Stripe webhook failing
```bash
# Check webhook secret
docker compose logs stripe-webhook

# Verify webhook endpoint
curl -X POST http://localhost:8000/api/payments/webhook/ \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Issue: Celery tasks not running
```bash
# Check Celery worker status
docker compose logs celery

# Restart Celery
docker compose restart celery celery-beat

# Check Flower dashboard
# Visit: http://localhost:5555
```

### Issue: Database connection error
```bash
# Wait for database
python manage.py wait_for_db

# Check database
docker compose exec db psql -U library_user -d library_db
```

---

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

---


## 👥 Authors

**Liliya Khudich-Tkachova**

---

## 🙏 Acknowledgments

- Django REST Framework
- Stripe API
- Telegram Bot API
- Celery
- Redis

---

## 📚 Additional Resources

- [Django Documentation](https://docs.djangoproject.com/)
- [DRF Documentation](https://www.django-rest-framework.org/)
- [Stripe Documentation](https://stripe.com/docs)
- [Celery Documentation](https://docs.celeryproject.org/)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---
