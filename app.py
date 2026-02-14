from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import requests
from pydantic import BaseModel
import itertools
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
host_cycle = itertools.cycle(ollama_hosts)
lock = threading.Lock()

class Host(BaseModel):
    url: str

class ModelCommand(BaseModel):
    model: str

def update_cycle():
    """Helper to refresh the round-robin iterator after host list changes"""
    global host_cycle
    host_cycle = itertools.cycle(ollama_hosts)

@app.post("/register")
def register_host(host: Host):
    with lock:
        if host.url not in ollama_hosts:
            ollama_hosts.append(host.url)
            update_cycle()
            logger.info(f"Registered new host: {host.url} | Current hosts: {ollama_hosts}")
        else:
            logger.info(f"Host already registered: {host.url}")
    return {"status": "registered", "hosts": ollama_hosts}

@app.post("/unregister")
def unregister_host(host: Host):
    with lock:
        if host.url in ollama_hosts:
            ollama_hosts.remove(host.url)
            update_cycle()
            logger.info(f"Unregistered host: {host.url} | Remaining: {ollama_hosts}")
        else:
            logger.info(f"Host not found: {host.url}")
    return {"status": "unregistered", "hosts": ollama_hosts}

@app.get("/hosts")
def list_hosts():
    return {"hosts": ollama_hosts}

def forward_request(method: str, path: str, data: dict, host: str) -> requests.Response:
    url = f"{host.rstrip('/')}/{path.lstrip('/')}"
    start_time = time.time()

    # Use shorter timeout for normal inference, longer for pulling models
    timeout = 600 if "pull" in path else 60

    try:
        if method == "GET":
            response = requests.get(url, params=data if data else None, stream=True, timeout=timeout)
        elif method == "POST":
            response = requests.post(url, json=data, stream=True, timeout=timeout)
        else:
            raise ValueError(f"Unsupported method: {method}")

        response.raise_for_status()
        duration = time.time() - start_time
        logger.info(f"Success → {host} | {method} /{path} | {duration:.3f}s")
        return response

    except requests.RequestException as e:
        duration = time.time() - start_time
        logger.error(f"Failed → {host} | {method} /{path} | {duration:.3f}s | Error: {str(e)}")
        raise HTTPException(status_code=502, detail=f"Host {host} failed: {str(e)}")

def get_next_host() -> str:
    with lock:
        if not ollama_hosts:
            raise HTTPException(status_code=503, detail="No Ollama hosts registered")
        host = next(host_cycle)
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
            response = forward_request(request.method, path, data, current_host)
            duration_total = time.time() - start_total
            logger.info(f"Total request time: {duration_total:.3f}s | Path: /{path} | Host: {current_host}")

            def stream_gen():
                for chunk in response.iter_content(chunk_size=1024):
                    yield chunk

            return StreamingResponse(
                stream_gen(),
                media_type=response.headers.get("Content-Type", "application/json"),
                status_code=response.status_code
            )

        except HTTPException as e:
            logger.warning(f"Failed on {current_host}, trying next")

            with lock:
                next_candidate = next(host_cycle)

            # Avoid infinite loop - stop if we've tried everyone
            if next_candidate in tried_hosts:
                raise HTTPException(status_code=503, detail="All available hosts failed")

            current_host = next_candidate


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)