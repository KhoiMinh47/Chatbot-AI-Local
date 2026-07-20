#!/usr/bin/env bash
set -euo pipefail

# Bootstrap and start all project services.
# Features:
# - Install Python dependencies into per-service venv if missing.
# - Install frontend dependencies.
# - Ensure vLLM image exists (build local image or pull remote image).
# - Check GeoIP database files (optional auto-download via env URLs).
# - Start docker compose services.
# - Auto-restore latest backup on first run (optional).

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-}"
RUNTIME_DIR="${RUNTIME_DIR:-.runtime}"
RESTORE_MARKER_FILE="$RUNTIME_DIR/restore_completed.marker"

if [[ -z "$ENV_FILE" ]]; then
  if [[ "$COMPOSE_FILE" == "docker-compose.all.yml" && -f ".env.all" ]]; then
    ENV_FILE=".env.all"
  else
    ENV_FILE=".env"
  fi
fi

# Behavior flags (override via env when needed)
SETUP_LOCAL_DEPS="${SETUP_LOCAL_DEPS:-true}"
SETUP_FRONTEND_DEPS="${SETUP_FRONTEND_DEPS:-true}"
SETUP_PYTHON_DEPS="${SETUP_PYTHON_DEPS:-true}"
AUTO_RESTORE_ON_FIRST_RUN="${AUTO_RESTORE_ON_FIRST_RUN:-false}"
GEOIP_AUTO_DOWNLOAD="${GEOIP_AUTO_DOWNLOAD:-true}"
GEOIP_STRICT="${GEOIP_STRICT:-true}"
RUN_CODE_SERVICES="${RUN_CODE_SERVICES:-true}"
CODE_TMUX_SESSION="${CODE_TMUX_SESSION:-rag-chat-code}"
BACKEND_TMUX_WINDOW="${BACKEND_TMUX_WINDOW:-backend}"
FRONTEND_TMUX_WINDOW="${FRONTEND_TMUX_WINDOW:-frontend}"
PARSER_TMUX_WINDOW="${PARSER_TMUX_WINDOW:-parse-data}"
EMBEDDING_TMUX_WINDOW="${EMBEDDING_TMUX_WINDOW:-embedding}"
PROMETHEUS_COLLECTOR_TMUX_WINDOW="${PROMETHEUS_COLLECTOR_TMUX_WINDOW:-prometheus-collector}"
FRONTEND_BUILD_ON_START="${FRONTEND_BUILD_ON_START:-true}"
FRONTEND_RUN_PORT="${FRONTEND_RUN_PORT:-3100}"

# docker-compose.all.yml đã có đầy đủ custom services chạy bằng Docker image.
# Mặc định chỉ bật tmux code-services khi chạy compose local.
if [[ "${RUN_CODE_SERVICES}" == "true" && "$COMPOSE_FILE" == "docker-compose.all.yml" ]]; then
  RUN_CODE_SERVICES="false"
fi

ensure_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing command '$cmd'. Please install it first."
    exit 1
  fi
}

ensure_file() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    echo "ERROR: Required file not found: $file_path"
    exit 1
  fi
}

setup_python_service() {
  local service_dir="$1"
  local req_file="$service_dir/requirements.txt"
  local venv_dir="$service_dir/venv"

  if [[ ! -f "$req_file" ]]; then
    return 0
  fi

  echo "[deps] Python service: $service_dir"
  if [[ ! -d "$venv_dir" ]]; then
    python3 -m venv "$venv_dir"
  fi

  "$venv_dir/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$venv_dir/bin/pip" install -r "$req_file"
}

setup_local_dependencies() {
  if [[ "$SETUP_LOCAL_DEPS" != "true" ]]; then
    echo "[deps] Skip local dependency setup (SETUP_LOCAL_DEPS=false)"
    return 0
  fi

  if [[ "$SETUP_PYTHON_DEPS" == "true" ]]; then
    ensure_cmd python3
    setup_python_service "backend"
    setup_python_service "parse-data"
    setup_python_service "embedding"
    setup_python_service "prometheus-collector"
  fi

  if [[ "$SETUP_FRONTEND_DEPS" == "true" ]]; then
    if command -v npm >/dev/null 2>&1; then
      echo "[deps] Frontend: frontend"
      (cd frontend && npm install)
    else
      echo "WARN: npm not found. Run frontend/setup_node.sh, then rerun this script."
    fi
  fi
}

load_env_if_exists() {
  if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1091
    set -a && source "$ENV_FILE" && set +a
  fi
}

ensure_vllm_image() {
  local vllm_image="${VLLM_IMAGE:-vllm/vllm-openai:latest}"

  echo "[vllm] Target image: $vllm_image"
  if docker image inspect "$vllm_image" >/dev/null 2>&1; then
    echo "[vllm] Image already exists locally"
    return 0
  fi

  if [[ "$vllm_image" == local/* ]] && [[ -f "docker/vllm-gemma4/Dockerfile" ]]; then
    echo "[vllm] Local image missing -> building from docker/vllm-gemma4/Dockerfile"
    docker build -t "$vllm_image" -f docker/vllm-gemma4/Dockerfile .
    return 0
  fi

  echo "[vllm] Image missing -> pulling from registry"
  docker pull "$vllm_image"
}

ensure_geoip_files() {
  local geoip_dir="backend/database/geoip"
  local city_file="$geoip_dir/GeoLite2-City.mmdb"
  local asn_file="$geoip_dir/GeoLite2-ASN.mmdb"
  local tmp_dir
  tmp_dir="$(mktemp -d)"

  cleanup_tmp() {
    rm -rf "$tmp_dir"
  }

  download_maxmind_edition() {
    local edition="$1"
    local output_mmdb="$2"
    local archive="$tmp_dir/${edition}.tar.gz"
    local extract_dir="$tmp_dir/${edition}"

    mkdir -p "$extract_dir"
    curl -fL \
      "https://download.maxmind.com/app/geoip_download?edition_id=${edition}&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz" \
      -o "$archive"

    tar -xzf "$archive" -C "$extract_dir"
    local found_mmdb
    found_mmdb="$(find "$extract_dir" -type f -name "${edition}.mmdb" | head -n 1 || true)"
    if [[ -z "$found_mmdb" ]]; then
      echo "ERROR: Cannot find ${edition}.mmdb in downloaded archive"
      exit 1
    fi
    cp "$found_mmdb" "$output_mmdb"
  }

  trap cleanup_tmp RETURN

  mkdir -p "$geoip_dir"

  if [[ -f "$city_file" && -f "$asn_file" ]]; then
    echo "[geoip] GeoIP files already present"
    return 0
  fi

  if [[ "$GEOIP_AUTO_DOWNLOAD" == "true" ]]; then
    ensure_cmd curl
    ensure_cmd tar
    if [[ -n "${GEOIP_CITY_DB_URL:-}" && -n "${GEOIP_ASN_DB_URL:-}" ]]; then
      echo "[geoip] Downloading GeoIP databases from configured URLs"
      curl -fL "$GEOIP_CITY_DB_URL" -o "$city_file"
      curl -fL "$GEOIP_ASN_DB_URL" -o "$asn_file"
      echo "[geoip] Download completed"
      return 0
    fi

    if [[ -n "${MAXMIND_LICENSE_KEY:-}" ]]; then
      echo "[geoip] Downloading GeoIP databases from MaxMind"
      download_maxmind_edition "GeoLite2-City" "$city_file"
      download_maxmind_edition "GeoLite2-ASN" "$asn_file"
      echo "[geoip] Download completed"
      return 0
    fi

    echo "WARN: GEOIP_AUTO_DOWNLOAD=true but GEOIP_CITY_DB_URL/GEOIP_ASN_DB_URL not set"
    echo "WARN: You can also set MAXMIND_LICENSE_KEY to auto-download from MaxMind"
  fi

  if [[ "$GEOIP_STRICT" == "true" ]]; then
    echo "ERROR: Missing GeoIP files and auto-download did not complete."
    [[ ! -f "$city_file" ]] && echo "  - $city_file"
    [[ ! -f "$asn_file" ]] && echo "  - $asn_file"
    echo "ERROR: Provide MAXMIND_LICENSE_KEY (or GEOIP_*_DB_URL), then rerun."
    exit 1
  fi

  echo "WARN: Missing GeoIP files:"
  [[ ! -f "$city_file" ]] && echo "  - $city_file"
  [[ ! -f "$asn_file" ]] && echo "  - $asn_file"
  echo "WARN: Backend still runs, but IP geolocation/monitoring will be degraded."
}

auto_restore_latest_backup_once() {
  if [[ "$AUTO_RESTORE_ON_FIRST_RUN" != "true" ]]; then
    echo "[restore] Skip auto restore (AUTO_RESTORE_ON_FIRST_RUN=false)"
    return 0
  fi

  mkdir -p "$RUNTIME_DIR"
  if [[ -f "$RESTORE_MARKER_FILE" ]]; then
    echo "[restore] Restore marker exists -> skip auto restore"
    return 0
  fi

  if [[ ! -d "backups" ]]; then
    echo "[restore] No backups directory found -> skip auto restore"
    return 0
  fi

  local latest_backup
  latest_backup="$(find backups -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1 || true)"
  if [[ -z "$latest_backup" ]]; then
    echo "[restore] No backup folder found inside backups/ -> skip auto restore"
    return 0
  fi

  echo "[restore] First run detected -> restoring from: $latest_backup"
  ensure_file "restore.sh"
  bash ./restore.sh "$latest_backup"
  date +%F_%H%M%S > "$RESTORE_MARKER_FILE"
  echo "[restore] Auto restore completed"
}

build_tmux_service_command() {
  local service_dir="$1"
  local service_cmd="$2"
  local log_file="$3"

  cat <<EOF
cd '$PROJECT_ROOT/$service_dir' && \
mkdir -p '$PROJECT_ROOT/$RUNTIME_DIR/logs' && \
touch '$log_file' && \
echo "===== [\$(date '+%F %T')] start $service_dir =====" >> '$log_file' && \
if [[ -f '$PROJECT_ROOT/$ENV_FILE' ]]; then set -a; source '$PROJECT_ROOT/$ENV_FILE'; set +a; fi && \
exec bash -lc "$service_cmd" >> '$log_file' 2>&1
EOF
}

start_code_services_tmux() {
  if [[ "$RUN_CODE_SERVICES" != "true" ]]; then
    echo "[tmux] Skip code services (RUN_CODE_SERVICES=false)"
    return 0
  fi

  ensure_cmd tmux

  local logs_dir="$PROJECT_ROOT/$RUNTIME_DIR/logs"
  mkdir -p "$logs_dir"

  local frontend_cmd="npm run start -- --port ${FRONTEND_RUN_PORT}"
  if [[ "$FRONTEND_BUILD_ON_START" == "true" ]]; then
    frontend_cmd="npm run build && ${frontend_cmd}"
  fi

  local backend_cmd="./venv/bin/python main.py"
  local parse_cmd="./venv/bin/python main.py"
  local embedding_cmd="./venv/bin/python main.py"
  local prom_cmd="./venv/bin/python main.py"

  echo "[tmux] (re)creating session: $CODE_TMUX_SESSION"
  tmux kill-session -t "$CODE_TMUX_SESSION" >/dev/null 2>&1 || true

  tmux new-session -d -s "$CODE_TMUX_SESSION" -n "$BACKEND_TMUX_WINDOW" \
    "$(build_tmux_service_command "backend" "$backend_cmd" "$logs_dir/backend.log")"

  tmux new-window -t "$CODE_TMUX_SESSION" -n "$FRONTEND_TMUX_WINDOW" \
    "$(build_tmux_service_command "frontend" "$frontend_cmd" "$logs_dir/frontend.log")"

  tmux new-window -t "$CODE_TMUX_SESSION" -n "$PARSER_TMUX_WINDOW" \
    "$(build_tmux_service_command "parse-data" "$parse_cmd" "$logs_dir/parse-data.log")"

  tmux new-window -t "$CODE_TMUX_SESSION" -n "$EMBEDDING_TMUX_WINDOW" \
    "$(build_tmux_service_command "embedding" "$embedding_cmd" "$logs_dir/embedding.log")"

  tmux new-window -t "$CODE_TMUX_SESSION" -n "$PROMETHEUS_COLLECTOR_TMUX_WINDOW" \
    "$(build_tmux_service_command "prometheus-collector" "$prom_cmd" "$logs_dir/prometheus-collector.log")"

  echo "[tmux] Session ready: $CODE_TMUX_SESSION"
  echo "[tmux] Attach: tmux attach -t $CODE_TMUX_SESSION"
  echo "[tmux] Logs: $logs_dir"
}

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "ERROR: Compose file not found: $COMPOSE_FILE"
  exit 1
fi

ensure_cmd docker

echo "[step 1/7] Loading .env (if exists)"
load_env_if_exists

echo "[step 2/7] Setting up local dependencies"
setup_local_dependencies

echo "[step 3/7] Ensuring vLLM image"
ensure_vllm_image

echo "[step 4/7] Checking GeoIP files"
ensure_geoip_files

echo "[step 5/7] Bringing up all Docker Compose services"
if [[ -f "$ENV_FILE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
else
  docker compose -f "$COMPOSE_FILE" up -d
fi

echo "[step 6/7] Auto restore backup on first run (if available)"
auto_restore_latest_backup_once

echo "[step 7/7] Starting code services in tmux (if enabled)"
start_code_services_tmux

echo
echo "Running containers:"
if [[ -f "$ENV_FILE" ]]; then
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
else
  docker compose -f "$COMPOSE_FILE" ps
fi

echo
echo "Access app via nginx reverse proxy:"
echo "  - http://localhost:${NGINX_PUBLIC_PORT:-3000}"
if [[ "$RUN_CODE_SERVICES" == "true" ]]; then
  echo "Code services tmux session: $CODE_TMUX_SESSION"
fi
