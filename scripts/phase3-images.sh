#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
ENV_FILE=${PHASE3_ENV_FILE:-$ROOT_DIR/infra/compose/phase3.env}
ACTION=${1:-check}
SCOPE=${2:-all}
PULL_TIMEOUT_SECONDS=${PHASE3_IMAGE_PULL_TIMEOUT_SECONDS:-3600}
PULL_ATTEMPTS=${PHASE3_IMAGE_PULL_ATTEMPTS:-3}

EXPECTED_IMAGE_ASSIGNMENTS=(
  "NIM_LLM_LLAMA_IMAGE=nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6@sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81"
  "NIM_LLM_NEMOTRON_IMAGE=nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant@sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"
  "NIM_EMBED_300M_IMAGE=nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2:1.13.0@sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4"
  "NIM_RERANK_500M_IMAGE=nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2:1.1@sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3"
)
EXPECTED_ARM64_ASSIGNMENTS=(
  "NIM_LLM_LLAMA_ARM64_DIGEST=sha256:249dcac461f20bc29ddb0924bf0c30e0e3f646c26bd849d978996cbe30b4d06e"
  "NIM_LLM_NEMOTRON_ARM64_DIGEST=sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4"
  "NIM_EMBED_300M_ARM64_DIGEST=sha256:5f8274faf21418cd894eb073d2c520923cce61a750c173b3745aedd1bb7efa49"
  "NIM_RERANK_500M_ARM64_DIGEST=sha256:6a598c5e6e7620c542f2101e24e34f3461e650a5b751200df56d52bf9f9444a9"
)
IMAGE_SCOPES=(llama nemotron retriever retriever)

if [[ ! -f $ENV_FILE ]]; then
  printf 'Phase 3 environment file is missing: %s\n' "$ENV_FILE" >&2
  exit 2
fi
for tool in docker jq timeout; do
  command -v "$tool" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$tool" >&2
    exit 127
  }
done
if [[ ! $PULL_TIMEOUT_SECONDS =~ ^[1-9][0-9]*$ ]]; then
  printf 'PHASE3_IMAGE_PULL_TIMEOUT_SECONDS must be a positive integer.\n' >&2
  exit 2
fi
if [[ ! $PULL_ATTEMPTS =~ ^[1-9][0-9]*$ ]]; then
  printf 'PHASE3_IMAGE_PULL_ATTEMPTS must be a positive integer.\n' >&2
  exit 2
fi
if [[ $ACTION != check && $ACTION != stage ]] || \
  [[ $SCOPE != all && $SCOPE != llama && $SCOPE != nemotron && $SCOPE != retriever ]]; then
  printf 'Usage: %s [check|stage] [all|llama|nemotron|retriever]\n' \
    "${BASH_SOURCE[0]}" >&2
  exit 2
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

IMAGE_REFS=()
for assignment in "${EXPECTED_IMAGE_ASSIGNMENTS[@]}"; do
  variable_name=${assignment%%=*}
  expected_ref=${assignment#*=}
  actual_ref=${!variable_name:-}
  if [[ $actual_ref != "$expected_ref" ]]; then
    printf 'Phase 3 image assignment drifted from reviewed ARM64 evidence: %s\n' \
      "$variable_name" >&2
    exit 1
  fi
  if [[ $actual_ref == *:latest* || ! $actual_ref =~ :[^/@]+@sha256:[0-9a-f]{64}$ ]]; then
    printf 'Refusing an unpinned or malformed Phase 3 image assignment: %s\n' \
      "$variable_name" >&2
    exit 1
  fi
  IMAGE_REFS+=("$actual_ref")
done

ARM64_DIGESTS=()
for assignment in "${EXPECTED_ARM64_ASSIGNMENTS[@]}"; do
  variable_name=${assignment%%=*}
  expected_digest=${assignment#*=}
  actual_digest=${!variable_name:-}
  if [[ $actual_digest != "$expected_digest" ]]; then
    printf 'Phase 3 ARM64 manifest evidence drifted: %s\n' "$variable_name" >&2
    exit 1
  fi
  ARM64_DIGESTS+=("$actual_digest")
done

if [[ $ACTION == stage ]]; then
  "$ROOT_DIR/scripts/phase3-secrets.sh" check >/dev/null
fi

for index in "${!IMAGE_REFS[@]}"; do
  if [[ $SCOPE != all && ${IMAGE_SCOPES[$index]} != "$SCOPE" ]]; then
    continue
  fi
  image=${IMAGE_REFS[$index]}
  arm64_digest=${ARM64_DIGESTS[$index]}
  tagged_ref=${image%@*}
  index_digest=${image##*@}
  repository=${tagged_ref%:*}
  expected_repo_digest=$repository@$index_digest

  if [[ $ACTION == stage ]]; then
    if ! manifest_json=$(docker manifest inspect --verbose "$tagged_ref"); then
      printf 'Unable to inspect the reviewed registry tag before staging: %s\n' \
        "$tagged_ref" >&2
      exit 1
    fi
    if ! jq -e --arg digest "$arm64_digest" '
      if type == "array" then
        any(.[];
          (.Descriptor.digest // "") == $digest and
          (.Descriptor.platform.os // .Descriptor.platform.OS // "") == "linux" and
          (.Descriptor.platform.architecture //
            .Descriptor.platform.Architecture // "") == "arm64")
      else
        ((.Descriptor.digest // "") == $digest and
          (.Descriptor.platform.os // .Descriptor.platform.OS // "") == "linux" and
          (.Descriptor.platform.architecture //
            .Descriptor.platform.Architecture // "") == "arm64") or
        any(.SchemaV2Manifest.manifests[]?;
          .digest == $digest and .platform.os == "linux" and
          .platform.architecture == "arm64")
      end
    ' <<<"$manifest_json" >/dev/null; then
      printf 'Registry tag no longer exposes the reviewed linux/arm64 manifest: %s\n' \
        "$tagged_ref" >&2
      exit 1
    fi
    unset manifest_json

    printf 'Staging reviewed linux/arm64 tag: %s\n' "$tagged_ref"
    pull_succeeded=0
    for ((attempt = 1; attempt <= PULL_ATTEMPTS; attempt++)); do
      if timeout --signal=TERM --kill-after=30s "${PULL_TIMEOUT_SECONDS}s" \
        docker pull --platform linux/arm64 "$tagged_ref"; then
        pull_succeeded=1
        break
      fi
      printf 'Pinned image pull attempt %s/%s failed; cached layers can resume.\n' \
        "$attempt" "$PULL_ATTEMPTS" >&2
    done
    if ((pull_succeeded == 0)); then
      printf 'Unable to stage the reviewed image after %s attempts: %s\n' \
        "$PULL_ATTEMPTS" "$tagged_ref" >&2
      exit 1
    fi
  elif ! docker image inspect "$image" >/dev/null 2>&1; then
    if [[ $ACTION == check ]]; then
      printf 'Pinned Phase 3 image is not staged locally: %s\n' "$image" >&2
      exit 1
    fi
  fi

  if ! docker image inspect "$image" >/dev/null 2>&1; then
    printf 'Staged tag does not resolve to the reviewed index digest: %s\n' "$image" >&2
    exit 1
  fi
  platform=$(docker image inspect "$image" --format '{{.Os}}/{{.Architecture}}')
  if [[ $platform != linux/arm64 ]]; then
    printf 'Pinned Phase 3 image has unexpected platform %s: %s\n' "$platform" "$image" >&2
    exit 1
  fi

  repo_digests=$(docker image inspect "$image" --format '{{json .RepoDigests}}')
  if ! jq -e --arg digest "$expected_repo_digest" 'index($digest) != null' \
    <<<"$repo_digests" >/dev/null; then
    printf 'Local image metadata does not contain the reviewed index digest: %s\n' \
      "$expected_repo_digest" >&2
    exit 1
  fi
done

if [[ $ACTION == stage ]]; then
  printf 'All reviewed Phase 3 image manifests are staged for linux/arm64.\n'
else
  printf 'All reviewed Phase 3 image manifests are present for linux/arm64.\n'
fi
