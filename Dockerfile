FROM python:3.11.6-alpine3.18
LABEL maintainer="liliyakhu@ukr.net"

ENV PYTHONUNBUFFERED=1

WORKDIR app/

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

# Create logs directory
RUN mkdir -p /app/logs

RUN adduser \
    --disabled-password \
    --no-create-home \
    my_user

# Give my_user ownership of the app directory (including logs)
RUN chown -R my_user:my_user /app

USER my_user
