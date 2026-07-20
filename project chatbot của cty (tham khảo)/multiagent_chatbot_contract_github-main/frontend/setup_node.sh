#!/bin/bash
# ==============================================================================
# Script cài đặt Node.js + npm local (không cần sudo)
# Sử dụng NVM (Node Version Manager)
# ==============================================================================

set -e

NODE_VERSION="20"  # LTS version

echo "=========================================="
echo "  Cài đặt NVM + Node.js v${NODE_VERSION}"
echo "=========================================="

# 1. Cài NVM nếu chưa có
if [ ! -d "$HOME/.nvm" ]; then
    echo "[1/3] Đang cài NVM..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
else
    echo "[1/3] NVM đã có sẵn."
fi

# 2. Load NVM vào shell hiện tại
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# 3. Cài Node.js
echo "[2/3] Đang cài Node.js v${NODE_VERSION}..."
nvm install $NODE_VERSION
nvm use $NODE_VERSION
nvm alias default $NODE_VERSION

echo "[3/3] Kiểm tra cài đặt:"
echo "  Node: $(node -v)"
echo "  NPM:  $(npm -v)"

echo ""
echo "=========================================="
echo "  CÀI ĐẶT THÀNH CÔNG!"
echo "=========================================="
echo ""
echo "Bước tiếp theo:"
echo "  1. Chạy lệnh sau để load NVM vào terminal hiện tại:"
echo "     source ~/.nvm/nvm.sh"
echo ""
echo "  2. Cài dependencies và chạy frontend:"
echo "     cd $(pwd)"
echo "     npm install"
echo "     npm run dev"
echo ""
