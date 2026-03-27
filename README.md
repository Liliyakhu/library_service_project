# library_service_project

## To run webhooks:
This is needed for receiving telegram notifications 
about maid payments (logic in payments/webhooks.py file)
### 1. in command line run:
stripe listen --forward-to localhost:8000/api/payments/webhook/
### 2. create borrowing and pay -> you receive a notification


## To run celery:
celery -A library_service worker -l INFO

## To run celery beat (using periodic tasks on admin page):
celery -A library_service beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler

## To run tests summary:
pytest --cov=. --cov-report=term | grep 'TOTAL'
## To run detailed info of tests coverage:
pytest --cov=. --cov-report=term-missing