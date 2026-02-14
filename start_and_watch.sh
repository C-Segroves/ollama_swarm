#!/bin/bash
# Start ollama_swarm container and watch logs

set -e

echo "=== Starting Ollama Swarm ==="
echo ""

# Stop and remove existing container if it exists
echo "1. Cleaning up existing container..."
docker stop ollama_swarm 2>/dev/null || echo "   No running container named 'ollama_swarm'"
docker rm ollama_swarm 2>/dev/null || echo "   No container to remove"

# Remove existing image if it exists (optional - comment out if you want to keep it)
echo "2. Removing old image..."
docker rmi ollama_swarm 2>/dev/null || echo "   No image to remove"

echo ""
echo "3. Building new Docker image..."
docker build -t ollama_swarm -f dockerfile .

echo ""
echo "4. Starting container..."
docker run -d --name ollama_swarm -p 8000:8000 ollama_swarm

echo ""
echo "=== Container Started! ==="
echo ""
echo "Container status:"
docker ps --filter "name=ollama_swarm" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "Waiting 2 seconds for container to initialize..."
sleep 2
echo ""
echo "=== Watching logs (Ctrl+C to stop watching, container will keep running) ==="
echo ""
docker logs -f ollama_swarm

