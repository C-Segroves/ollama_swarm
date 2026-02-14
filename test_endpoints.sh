#!/bin/bash
# Test script for all ollama_swarm endpoints

BASE_URL="http://localhost:8000"
echo "Testing Ollama Swarm Endpoints"
echo "================================"
echo ""

# Test 1: GET /hosts - List registered hosts
echo "1. Testing GET /hosts"
echo "-------------------"
curl -s "$BASE_URL/hosts" | python3 -m json.tool
echo -e "\n"

# Test 2: GET /admin/list_models - List models from all hosts
echo "2. Testing GET /admin/list_models"
echo "--------------------------------"
RESULT=$(curl -s "$BASE_URL/admin/list_models")
echo "$RESULT" | python3 -m json.tool | head -50
echo -e "\n"

# Test 3: POST /register - Register a host (test with existing host)
echo "3. Testing POST /register (with already registered host)"
echo "-------------------------------------------------------"
curl -s -X POST "$BASE_URL/register" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://192.168.1.204:11434"}' | python3 -m json.tool
echo -e "\n"

# Test 4: POST /register - Register a new host (test host)
echo "4. Testing POST /register (with test host)"
echo "-------------------------------------------"
curl -s -X POST "$BASE_URL/register" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://test.example.com:11434"}' | python3 -m json.tool
echo -e "\n"

# Test 5: GET /hosts - Verify new host was added
echo "5. Testing GET /hosts (after registration)"
echo "-----------------------------------------"
curl -s "$BASE_URL/hosts" | python3 -m json.tool
echo -e "\n"

# Test 6: POST /unregister - Remove test host
echo "6. Testing POST /unregister"
echo "--------------------------"
curl -s -X POST "$BASE_URL/unregister" \
  -H "Content-Type: application/json" \
  -d '{"url": "http://test.example.com:11434"}' | python3 -m json.tool
echo -e "\n"

# Test 7: GET /hosts - Verify test host was removed
echo "7. Testing GET /hosts (after unregistration)"
echo "--------------------------------------------"
curl -s "$BASE_URL/hosts" | python3 -m json.tool
echo -e "\n"

# Test 8: POST /admin/pull - Test pull endpoint (with a small model or invalid model)
echo "8. Testing POST /admin/pull (this may take time or fail if model doesn't exist)"
echo "------------------------------------------------------------------------------"
curl -s -X POST "$BASE_URL/admin/pull" \
  -H "Content-Type: application/json" \
  -d '{"model": "test-model:latest"}' | python3 -m json.tool
echo -e "\n"

# Test 9: Proxy route - Test GET /api/tags through proxy
echo "9. Testing Proxy Route GET /api/tags"
echo "------------------------------------"
curl -s "$BASE_URL/api/tags" | python3 -m json.tool | head -30
echo -e "\n"

# Test 10: Proxy route - Test GET /api/version through proxy
echo "10. Testing Proxy Route GET /api/version"
echo "---------------------------------------"
curl -s "$BASE_URL/api/version" | python3 -m json.tool
echo -e "\n"

echo "================================"
echo "Endpoint testing complete!"

