#!/usr/bin/env bash

set -euo pipefail

health_path=${NTC_NIM_HEALTH_PATH:-/v1/health/ready}
health_port=${NTC_NIM_HEALTH_PORT:-8000}

if [[ ! $health_path =~ ^/[A-Za-z0-9._~/-]+$ ]]; then
  printf 'Invalid NIM health path.\n' >&2
  exit 2
fi
if [[ ! $health_port =~ ^[1-9][0-9]{0,4}$ ]] || ((health_port > 65535)); then
  printf 'Invalid NIM health port.\n' >&2
  exit 2
fi

exec 3<>"/dev/tcp/127.0.0.1/$health_port"
printf 'GET %s HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n' \
  "$health_path" >&3
IFS= read -r status_line <&3
exec 3>&- 3<&-

[[ $status_line =~ ^HTTP/[0-9.]+[[:space:]]+2[0-9][0-9]([[:space:]]|$) ]]
