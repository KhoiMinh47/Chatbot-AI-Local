#!/usr/bin/env sh

set -eu

# Read secrets from environment variables (with fallback to secret files for backwards compatibility)
password="${CELERY_BROKER_PASSWORD:-$([ -f /run/secrets/rabbitmq_password ] && cat /run/secrets/rabbitmq_password)}"
database_password="${WORKER_DATABASE_PASSWORD:-$([ -f /run/secrets/postgres_password ] && cat /run/secrets/postgres_password)}"
minio_secret="${WORKER_MINIO_SECRET_KEY:-$([ -f /run/secrets/minio_root_password ] && cat /run/secrets/minio_root_password)}"

if [ -z "$password" ] || [ -z "$database_password" ] || [ -z "$minio_secret" ]; then
  printf 'A required worker secret is missing or empty.\n' >&2
  exit 1
fi

host=${CELERY_BROKER_HOST:-rabbitmq}
port=${CELERY_BROKER_PORT:-5672}
user=${CELERY_BROKER_USER:-ntc_worker}
concurrency=${CELERY_WORKER_CONCURRENCY:-2}

database_host=${WORKER_DATABASE_HOST:-postgres}
database_port=${WORKER_DATABASE_PORT:-5432}
database_user=${WORKER_DATABASE_USER:-ntc_app}
database_name=${WORKER_DATABASE_NAME:-ntc_rag}
minio_endpoint=${WORKER_MINIO_ENDPOINT:-minio:9000}
minio_access_key=${WORKER_MINIO_ACCESS_KEY:-ntc_minio_admin}

case "$host:$port:$user:$concurrency:$password:$database_host:$database_port:$database_user:$database_name:$database_password:$minio_endpoint:$minio_access_key:$minio_secret" in
  *[!A-Za-z0-9_.:-]*)
    printf 'Worker runtime settings contain unsupported characters.\n' >&2
    exit 1
    ;;
esac

export CELERY_BROKER_URL="amqp://$user:$password@$host:$port//"
export DATABASE_URL="postgresql+psycopg://$database_user:$database_password@$database_host:$database_port/$database_name"
export MINIO_ENDPOINT="$minio_endpoint"
export MINIO_ACCESS_KEY="$minio_access_key"
export MINIO_SECRET_KEY="$minio_secret"
unset password database_password minio_secret

exec celery --app worker.runtime:celery worker \
  --loglevel=INFO \
  --concurrency="$concurrency" \
  --queues=ingestion \
  --hostname='ntc-worker@%h' \
  --without-gossip \
  --without-mingle
