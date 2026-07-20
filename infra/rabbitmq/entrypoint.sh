#!/usr/bin/env sh

set -eu

password_file=/run/secrets/rabbitmq_password
if [ ! -s "$password_file" ]; then
  printf 'RabbitMQ password secret is missing or empty.\n' >&2
  exit 1
fi
if [ -z "${RABBITMQ_DEFAULT_USER:-}" ]; then
  printf 'RABBITMQ_DEFAULT_USER must not be empty.\n' >&2
  exit 1
fi

password=$(cat "$password_file")
umask 077
mkdir -p /run/ntc-rabbitmq
cat > /run/ntc-rabbitmq/rabbitmq.conf <<EOF
default_user = $RABBITMQ_DEFAULT_USER
default_pass = $password
listeners.tcp.default = 5672
management.tcp.port = 15672
prometheus.tcp.port = 15692
EOF
chown -R rabbitmq:rabbitmq /run/ntc-rabbitmq
unset password
export RABBITMQ_CONFIG_FILE=/run/ntc-rabbitmq/rabbitmq

exec docker-entrypoint.sh rabbitmq-server
