#!/usr/bin/env sh

set -eu

host=${CELERY_BROKER_HOST:-rabbitmq}
port=${CELERY_BROKER_PORT:-5672}
user=${CELERY_BROKER_USER:-ntc_worker}

# Read password from env var first, fall back to secret file
if [ -n "${CELERY_BROKER_PASSWORD:-}" ]; then
  password="$CELERY_BROKER_PASSWORD"
elif [ -s /run/secrets/rabbitmq_password ]; then
  password=$(cat /run/secrets/rabbitmq_password)
else
  exit 1
fi

export CELERY_BROKER_URL="amqp://$user:$password@$host:$port//"
unset password

celery --app worker.runtime:celery inspect ping \
  --destination="ntc-worker@$(hostname)" \
  --timeout=3 2>/dev/null | grep -q pong
