#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPOSITORY_ROOT"

UV_BIN="${UV_BIN:-uv}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

set +e
check_output="$("$UV_BIN" pip check --python "$PYTHON_BIN" 2>&1)"
check_status=$?
set -e
printf '%s\n' "$check_output"

if [[ "$check_status" -eq 0 ]]; then
  exit 0
fi

# NVIDIA's 0.8.1 ARM64 wheel filename is manylinux2014_aarch64, and its shared
# object is AArch64, but the embedded WHEEL metadata uses the non-PEP tag
# manylinux2014_sbsa. uv correctly reports that tag as incompatible. Accept only
# this exact, fully verified upstream metadata mismatch; every other package or
# version remains a hard failure.
if [[ "$(uname -m)" != "aarch64" ]]; then
  exit "$check_status"
fi

# shellcheck disable=SC2016  # Backticks are literal uv diagnostic characters.
mapfile -t incompatibilities < <(
  sed -n 's/^\(The package `[^`]*` was built for a different platform\)$/\1/p' \
    <<<"$check_output"
)
# shellcheck disable=SC2016  # Backticks are literal uv diagnostic characters.
if [[ "${#incompatibilities[@]}" -ne 1 ]] || \
  [[ "${incompatibilities[0]}" != \
    'The package `nvidia-cusparselt-cu13` was built for a different platform' ]]; then
  exit "$check_status"
fi

version="$(
  "$PYTHON_BIN" -c \
    'from importlib.metadata import version; print(version("nvidia-cusparselt-cu13"))'
)"
if [[ "$version" != "0.8.1" ]]; then
  exit "$check_status"
fi

site_packages="$(
  "$PYTHON_BIN" -c \
    'import sysconfig; print(sysconfig.get_paths()["purelib"])'
)"
wheel_metadata="$site_packages/nvidia_cusparselt_cu13-0.8.1.dist-info/WHEEL"
library="$site_packages/nvidia/cusparselt/lib/libcusparseLt.so.0"

if [[ ! -f "$wheel_metadata" ]] || [[ ! -f "$library" ]]; then
  exit "$check_status"
fi
if [[ "$(sed -n 's/^Tag: //p' "$wheel_metadata")" != \
  "py3-none-manylinux2014_sbsa" ]]; then
  exit "$check_status"
fi
if ! readelf -h "$library" | grep -Eq '^  Machine:[[:space:]]+AArch64$'; then
  exit "$check_status"
fi
if ! grep -Eq \
  'nvidia_cusparselt_cu13-0\.8\.1-py3-none-manylinux2014_aarch64\.whl.*sha256:4dca476c50bf4780d46cd0bfbd82e2bc10a08e4fef7950917ce8d7578d22a23f' \
  uv.lock; then
  exit "$check_status"
fi

printf '%s\n' \
  'Accepted verified NVIDIA cuSPARSELt ARM64 wheel metadata deviation:' \
  'filename/lock and ELF are AArch64; embedded WHEEL tag is manylinux2014_sbsa.'
