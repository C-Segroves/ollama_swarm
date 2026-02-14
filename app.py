from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import httpx
import requests
from pydantic import BaseModel
import threading
from typing import List
import time
import logging

# Configure logging to stdout (appears in docker logs)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Ollama Swarm Proxy")

# Global state with lock protection
ollama_hosts: List[str] = []
lock = threading.Lock()
# Thread-safe counter for round-robin host selection
_host_counter = 0
_counter_lock = threading.Lock()

class Host(BaseModel):
    url: str

class ModelCommand(BaseModel):
    model: str

# Removed update_cycle - using atomic counter instead

@app.post("/register")
def register_host(host: Host):
    with lock:
        if host.url not in ollama_hosts:
            ollama_hosts.append(host.url)
            logger.info(f"Registered new host: {host.url} | Current hosts: {ollama_hosts}")
        else:
            logger.info(f"Host already registered: {host.url}")
    return {"status": "registered", "hosts": ollama_hosts}

@app.post("/unregister")
def unregister_host(host: Host):
    with lock:
        if host.url in ollama_hosts:
            ollama_hosts.remove(host.url)
            logger.info(f"Unregistered host: {host.url} | Remaining: {ollama_hosts}")
        else:
            logger.info(f"Host not found: {host.url}")
    return {"status": "unregistered", "hosts": ollama_hosts}

@app.get("/hosts")
def list_hosts():
    return {"hosts": ollama_hosts}

async def forward_request(method: str, path: str, data: dict, host: str, stream: bool = True):
    url = f"{host.rstrip('/')}/{path.lstrip('/')}"
    start_time = time.time()

    # Use shorter timeout for normal inference, longer for pulling models
    timeout = 600.0 if "pull" in path else 60.0

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(url, params=data if data else None, follow_redirects=True)
            elif method == "POST":
                response = await client.post(url, json=data, follow_redirects=True)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            duration = time.time() - start_time
            logger.info(f"Success → {host} | {method} /{path} | {duration:.3f}s")
            return response

    except httpx.RequestError as e:
        duration = time.time() - start_time
        logger.error(f"Failed → {host} | {method} /{path} | {duration:.3f}s | Error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Host {host} failed: {str(e)}")
    except httpx.HTTPStatusError as e:
        duration = time.time() - start_time
        logger.error(f"HTTP Error → {host} | {method} /{path} | {duration:.3f}s | Status: {e.response.status_code}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Host {host} returned error: {e.response.status_code}")

def get_next_host() -> str:
    """Get next host using thread-safe atomic counter for round-robin distribution"""
    global _host_counter
    
    # Get host count atomically and increment counter
    with _counter_lock:
        if not ollama_hosts:
            raise HTTPException(status_code=503, detail="No Ollama hosts registered")
        host_count = len(ollama_hosts)
        # Use modulo for round-robin, increment counter
        host = ollama_hosts[_host_counter % host_count]
        _host_counter += 1
    
    logger.info(f"Routing request to: {host}")
    return host

# ────────────────────────────────────────────────
# Admin endpoints (must be defined before catch-all route)
# ────────────────────────────────────────────────

@app.post("/admin/pull")
def admin_pull(model: ModelCommand):
    results = {}
    with lock:
        for host in ollama_hosts[:]:  # copy to avoid modification during iteration
            start = time.time()
            try:
                r = requests.post(
                    f"{host}/api/pull",
                    json={"model": model.model},
                    timeout=600,
                    stream=True
                )
                r.raise_for_status()
                results[host] = "success"
                logger.info(f"Pull success on {host} | {time.time()-start:.2f}s")
            except Exception as e:
                results[host] = f"failed: {str(e)}"
                logger.error(f"Pull failed on {host} | {time.time()-start:.2f}s | {str(e)}")
    return {"results": results}


@app.get("/admin/list_models")
def admin_list_models():
    results = {}
    with lock:
        for host in ollama_hosts:
            try:
                response = requests.get(f"{host}/api/tags", timeout=15)
                response.raise_for_status()
                results[host] = response.json()
            except requests.RequestException as e:
                results[host] = f"failed: {str(e)}"
    return {"results": results}

@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(request: Request, path: str):
    start_total = time.time()
    data = await request.json() if request.method == "POST" else {}

    # We'll try all hosts in worst case, but prefer round-robin start
    tried_hosts = []
    original_host = get_next_host()
    current_host = original_host

    while True:
        tried_hosts.append(current_host)

        try:
            response = await forward_request(request.method, path, data, current_host)
            duration_total = time.time() - start_total
            logger.info(f"Total request time: {duration_total:.3f}s | Path: /{path} | Host: {current_host}")

            # Stream the response content
            async def stream_gen():
                # Yield response content in chunks
                content = response.content
                chunk_size = 8192
                for i in range(0, len(content), chunk_size):
                    yield content[i:i + chunk_size]

            # Get content type, defaulting appropriately
            content_type = response.headers.get("Content-Type", "application/json")
            if "text/event-stream" in content_type or "application/x-ndjson" in content_type:
                # Preserve streaming content types
                pass

            return StreamingResponse(
                stream_gen(),
                media_type=content_type,
                status_code=response.status_code
            )

        except HTTPException as e:
            logger.warning(f"Failed on {current_host}, trying next")

            # Get next host for failover
            with lock:
                if not ollama_hosts:
                    raise HTTPException(status_code=503, detail="No Ollama hosts registered")
                # Find next host that hasn't been tried
                current_idx = ollama_hosts.index(current_host) if current_host in ollama_hosts else -1
                next_candidate = None
                for i in range(len(ollama_hosts)):
                    candidate_idx = (current_idx + i + 1) % len(ollama_hosts)
                    candidate = ollama_hosts[candidate_idx]
                    if candidate not in tried_hosts:
                        next_candidate = candidate
                        break

            # Avoid infinite loop - stop if we've tried everyone
            if next_candidate is None or next_candidate in tried_hosts:
                raise HTTPException(status_code=503, detail="All available hosts failed")

            current_host = next_candidate


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)