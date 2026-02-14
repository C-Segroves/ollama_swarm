#!/bin/bash
# Rebuild container and test all endpoints

set -e

echo "=========================================="
echo "OLLAMA SWARM - REBUILD AND TEST"
echo "=========================================="
echo ""

# Step 1: Rebuild
echo "STEP 1: Rebuilding Container"
echo "----------------------------"

# Stop and remove existing container
echo "Stopping existing containers..."
docker stop ollama_swarm 2>/dev/null || echo "  No container named 'ollama_swarm' found"
docker rm ollama_swarm 2>/dev/null || echo "  No container to remove"

CONTAINER_ON_PORT=$(docker ps -q --filter "publish=8000" 2>/dev/null || echo "")
if [ ! -z "$CONTAINER_ON_PORT" ]; then
    echo "  Stopping container on port 8000: $CONTAINER_ON_PORT"
    docker stop $CONTAINER_ON_PORT 2>/dev/null || true
    docker rm $CONTAINER_ON_PORT 2>/dev/null || true
fi

# Build image
echo "Building Docker image..."
docker build -t ollama_swarm -f dockerfile .

# Start container
echo "Starting container..."
docker run -d --name ollama_swarm -p 8000:8000 ollama_swarm

# Wait for container to be ready
echo "Waiting for container to start..."
sleep 3

echo ""
echo "Container status:"
docker ps --filter "name=ollama_swarm" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Step 2: Register servers
echo "STEP 2: Registering Ollama Servers"
echo "-----------------------------------"
curl -s -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.204:11434"}' | python3 -m json.tool

curl -s -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.166:11434"}' | python3 -m json.tool

echo ""

# Step 3: Test endpoints
echo "STEP 3: Testing All Endpoints"
echo "------------------------------"
echo ""

BASE_URL="http://localhost:8000"
PASSED=0
FAILED=0

test_endpoint() {
    local name=$1
    local method=$2
    local path=$3
    local data=$4
    
    echo "Testing: $name"
    echo "  $method $path"
    
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" "$BASE_URL$path")
    else
        response=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL$path" \
          -H "Content-Type: application/json" \
          -d "$data")
    fi
    
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | sed '$d')
    
    if [ "$http_code" -ge 200 ] && [ "$http_code" -lt 400 ]; then
        echo "  ✓ PASS (HTTP $http_code)"
        if echo "$body" | python3 -m json.tool > /dev/null 2>&1; then
            echo "$body" | python3 -m json.tool | head -10
        else
            echo "  Response: ${body:0:100}..."
        fi
        PASSED=$((PASSED + 1))
    else
        echo "  ✗ FAIL (HTTP $http_code)"
        echo "  Response: $body"
        FAILED=$((FAILED + 1))
    fi
    echo ""
}

# Test all endpoints
test_endpoint "List Hosts" "GET" "/hosts"
test_endpoint "Admin: List Models" "GET" "/admin/list_models"
test_endpoint "Register Host (duplicate)" "POST" "/register" '{"url": "http://192.168.1.204:11434"}'
test_endpoint "Proxy: List Models" "GET" "/api/tags"
test_endpoint "Proxy: Get Version" "GET" "/api/version"
test_endpoint "Admin: Pull Model" "POST" "/admin/pull" '{"model": "test-model:latest"}'

# Summary
echo "=========================================="
echo "TEST SUMMARY"
echo "=========================================="
echo "Passed: $PASSED"
echo "Failed: $FAILED"
echo "Total:  $((PASSED + FAILED))"
echo ""

if [ $FAILED -eq 0 ]; then
    echo "✓ All tests passed!"
    exit 0
else
    echo "✗ Some tests failed"
    exit 1
fi

