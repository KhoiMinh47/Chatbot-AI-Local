#!/usr/bin/env bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  NTC RAG Chatbot - One Command Start   ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"

# Step 1: Check if .env exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}→ Creating .env file...${NC}"
    cp .env.example .env 2>/dev/null || cat > .env << 'EOF'
POSTGRES_IMAGE=postgres:16-alpine
REDIS_IMAGE=redis:7-alpine
RABBITMQ_IMAGE=rabbitmq:3-management-alpine
MINIO_IMAGE=minio:latest
QDRANT_IMAGE=qdrant:latest
PYTHON_IMAGE=python:3.14.5-slim-bookworm@sha256:a9bee15510a364124aa24692899d269835683b883de42f7ebec8c293cf679ccb
NODE_IMAGE=node:20-alpine
UV_IMAGE=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d
PHASE2_SECRET_GID=1000
POSTGRES_USER=ntc_app
POSTGRES_PASSWORD=ntc_secure_pass_2024
POSTGRES_DB=ntc_rag
RABBITMQ_DEFAULT_USER=ntc_worker
RABBITMQ_DEFAULT_PASS=ntc_rabbitmq_pass_2024
MINIO_ROOT_USER=ntc_minio_admin
MINIO_ROOT_PASSWORD=ntc_minio_pass_2024
EOF
    echo -e "${GREEN}✓ .env created${NC}"
fi

# Step 2: Start Docker services
echo -e "\n${YELLOW}→ Starting Docker services...${NC}"
docker compose --profile core --profile app up -d 2>&1 | grep -E "Created|Running|Healthy|ERROR" | head -20

# Wait for services to be ready
echo -e "${YELLOW}→ Waiting for services to stabilize... (15s)${NC}"
sleep 15

# Step 3: Check service health
echo -e "\n${YELLOW}→ Checking service health...${NC}"
HEALTHY=0
for i in {1..5}; do
    HEALTHY=$(docker ps --format "table {{.Status}}" | grep -c "healthy" || echo 0)
    if [ "$HEALTHY" -ge 6 ]; then
        break
    fi
    sleep 3
done

docker ps --format "table {{.Names}}\t{{.Status}}" | grep km-taskchatbot | sed 's/^/  /'

# Step 4: Apply database migrations
echo -e "\n${YELLOW}→ Applying database migrations...${NC}"
docker compose exec -T postgres psql -U ntc_app -d ntc_rag -h localhost -c "SELECT 1" > /dev/null 2>&1 || {
    echo -e "${RED}✗ Database not ready${NC}"
    exit 1
}

# Apply migrations using alembic
if command -v alembic &> /dev/null; then
    echo -e "${YELLOW}  Running alembic migrations...${NC}"
    cd /home/ntcai/KM\ -\ Task\ Chatbot
    source .venv/bin/activate 2>/dev/null || true
    alembic upgrade head 2>&1 | tail -3
fi

echo -e "${GREEN}✓ Database ready${NC}"

# Step 5: Show access information
echo -e "\n${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✓ NTC RAG Chatbot is Running!         ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}🌐 Web UI:${NC}        http://localhost:3000"
echo -e "${BLUE}📚 API Docs:${NC}      http://localhost:8000/docs"
echo -e "${BLUE}🔧 RabbitMQ:${NC}     http://localhost:15672 (guest/guest)"
echo -e "${BLUE}📊 MinIO:${NC}        http://localhost:9001"
echo ""
echo -e "${YELLOW}Services Status:${NC}"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep km-taskchatbot | awk '{print "  " $1 "\t" $2}' | sed 's/km-taskchatbot-//' | sed 's/-1//'

echo ""
echo -e "${YELLOW}To stop services: ${NC}docker compose down"
echo -e "${YELLOW}To view logs:     ${NC}docker compose logs -f api"
echo ""
