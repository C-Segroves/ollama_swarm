#!/bin/bash
# Rebuild script for ollama_swarm Docker container

set -e

echo "=== Rebuilding Ollama Swarm Container ==="
echo ""

# Stop and remove existing container
echo "1. Stopping existing containers..."
docker stop ollama_swarm 2>/dev/null || echo "   No container named 'ollama_swarm'"
docker rm ollama_swarm 2>/dev/null || echo "   No container to remove"

# Stop any container using port 8000
CONTAINER_ON_PORT=$(docker ps -q --filter "publish=8000" 2>/dev/null || echo "")
if [ ! -z "$CONTAINER_ON_PORT" ]; then
    echo "   Stopping container on port 8000: $CONTAINER_ON_PORT"
    docker stop $CONTAINER_ON_PORT 2>/dev/null || true
    docker rm $CONTAINER_ON_PORT 2>/dev/null || true
fi

echo ""

# Build the Docker image
echo "2. Building Docker image..."
docker build -t ollama_swarm -f dockerfile .

echo ""

# Start the new container
echo "3. Starting new container..."
docker run -d --name ollama_swarm -p 8000:8000 ollama_swarm

echo ""
echo "=== Rebuild Complete! ==="
echo ""
echo "Container status:"
docker ps --filter "name=ollama_swarm" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "Waiting 3 seconds for container to start..."
sleep 3
echo ""
echo "Testing admin endpoint..."
curl -s http://localhost:8000/admin/list_models | python3 -m json.tool | head -20 || echo "Endpoint test failed"
