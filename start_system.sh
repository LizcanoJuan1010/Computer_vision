#!/bin/bash

# Colors
set -e
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Starting VIGIAS-IA System ===${NC}"

# Check directories
if [ ! -d "black_list" ]; then
    mkdir black_list
    echo "Created black_list/ directory."
fi

# Load .env
if [ -f ../.env ]; then
    export $(cat ../.env | grep -v '#' | awk '/=/ {print $1}')
elif [ -f .env ]; then
    export $(cat .env | grep -v '#' | awk '/=/ {print $1}')
fi

# Create Network
echo -e "${BLUE}Configuring Docker Network...${NC}"
docker network inspect vision_net >/dev/null 2>&1 || docker network create vision_net

# Cleanup Old Containers
echo -e "${BLUE}Cleaning up old containers...${NC}"
docker rm -f nats redis postgres router ingest 2>/dev/null || true

# Start NATS
echo -e "${GREEN}Starting NATS...${NC}"
docker run -d --name nats \
  --network vision_net \
  -p 4223:4222 -p 8223:8222 \
  nats:latest -js

# Start Redis
echo -e "${GREEN}Starting Redis...${NC}"
docker run -d --name redis \
  --network vision_net \
  -p 6380:6379 \
  redis:7-alpine

# Start Postgres
echo -e "${GREEN}Starting Postgres...${NC}"
docker run -d --name postgres \
  --network vision_net \
  -p 5436:5432 \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=vigias \
  -v postgres_data:/var/lib/postgresql/data \
  pgvector/pgvector:pg16

# Build & Start Router
echo -e "${GREEN}Building & Starting Router...${NC}"
docker build -t vigias-router ./router
docker run -d --name router \
  --network vision_net \
  -p 8003:8000 \
  -e NATS_URL=nats://nats:4222 \
  -e REDIS_HOST=redis \
  -e REDIS_PORT=6379 \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_USER=user \
  -e DB_PASSWORD=password \
  -e DB_NAME=vigias \
  vigias-router

# Build & Start Ingest
echo -e "${GREEN}Building & Starting Ingest...${NC}"
docker build -t vigias-ingest ./ingest
docker run -d --name ingest \
  --network vision_net \
  -p 8081:8080 \
  -v $(pwd)/ingest/cameras.json:/app/cameras.json:ro \
  -e NATS_URL=nats://nats:4222 \
  -e CAMERAS_FILE=/app/cameras.json \
  -e DB_HOST=postgres \
  -e DB_PORT=5432 \
  -e DB_USER=user \
  -e DB_PASSWORD=password \
  -e DB_NAME=vigias \
  -e HIK_USER="$HIK_USER" \
  -e HIK_PASS="$HIK_PASS" \
  -e HIK_IP="$HIK_IP" \
  -e PORT_RTSP="$PORT_RTSP" \
  -e PORT_HTTP="$PORT_HTTP" \
  -e RESIZE_WIDTH=640 \
  -e RESIZE_HEIGHT=360 \
  -e TARGET_FPS=15.0 \
  -e RTSP_TRANSPORT="${RTSP_TRANSPORT:-tcp}" \
  vigias-ingest

echo -e "${GREEN}Infrastructure Running!${NC}"
echo "Waiting for services..."
sleep 5

# Wait for Postgres
until docker exec postgres pg_isready -U user; do
  echo "Waiting for Postgres..."
  sleep 2
done

echo "Initializing Database Schema..."
docker exec -i postgres psql -U user -d vigias < database/schema.sql

echo "Migrating/Initializing Database from cameras.json..."
DB_HOST=localhost DB_PORT=5436 DB_USER=user DB_PASSWORD=password DB_NAME=vigias \
/home/logisticos-two/dev/miniconda3/envs/vigias-ia/bin/python tools/migrate_json_to_db.py

echo "Seeding Redis configuration..."
DB_HOST=localhost DB_PORT=5436 DB_USER=user DB_PASSWORD=password DB_NAME=vigias \
/home/logisticos-two/dev/miniconda3/envs/vigias-ia/bin/python scripts/sync_config.py

# Trap for Shutdown
trap "echo 'Stopping System...'; docker rm -f nats redis postgres router ingest; exit" SIGINT SIGTERM

echo -e "${GREEN}Starting Inference Service (Native)...${NC}"
echo "Press Ctrl+C to stop everything."

export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/home/logisticos-two/dev/miniconda3/envs/vigias-ia/lib:/home/logisticos-two/dev/miniconda3/envs/vigias-ia/lib/python3.10/site-packages/nvidia/cuda_runtime/lib:/home/logisticos-two/dev/miniconda3/envs/vigias-ia/lib/python3.10/site-packages/nvidia/cudnn/lib:/home/logisticos-two/dev/miniconda3/envs/vigias-ia/lib/python3.10/site-packages/nvidia/cublas/lib:/home/logisticos-two/dev/miniconda3/envs/vigias-ia/lib/python3.10/site-packages/nvidia/cufft/lib:/home/logisticos-two/dev/miniconda3/envs/vigias-ia/lib/python3.10/site-packages/nvidia/curand/lib
export REDIS_URL="redis://localhost:6380/0"
export HEADLESS=false
# Override DB connection for local process
export DB_HOST=localhost
export DB_PORT=5436
export DB_USER=user
export DB_PASSWORD=password
export DB_NAME=vigias

/home/logisticos-two/dev/miniconda3/envs/vigias-ia/bin/python -m inference.main
