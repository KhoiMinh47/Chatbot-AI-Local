#!/usr/bin/env sh

set -eu

password_file=/run/secrets/redis_password
if [ ! -s "$password_file" ]; then
  printf 'Redis password secret is missing or empty.\n' >&2
  exit 1
fi

password=$(cat "$password_file")
umask 077
mkdir -p /run/ntc-redis
cat > /run/ntc-redis/redis.conf <<EOF
bind 0.0.0.0
protected-mode yes
port 6379
dir /data
appendonly yes
appendfsync everysec
save 60 1
requirepass $password
EOF
unset password
chown -R redis:redis /run/ntc-redis

exec docker-entrypoint.sh redis-server /run/ntc-redis/redis.conf
