from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
import requests
import json
from pydantic import BaseModel
import itertools
import threading
from typing import List

app = FastAPI(title="Ollama Swarm Proxy")

# In-memory list of Ollama hosts (e.g., ["http://192.168.1.204:11434", "http://192.168.1.246:11434", "http://192.168.1.166:11434"])
ollama_hosts: List[str] = []
host_cycle = itertools.cycle(ollama_hosts)  # For round-robin

# Lock for thread safety
lock = threading.Lock()

class Host(BaseModel):
    url: str  # e.g., "http://host:11434"

class ModelCommand(BaseModel):
    model: str

@app.post("/register")
def register_host(host: Host):
    with lock:
        if host.url not in ollama_hosts:
            ollama_hosts.append(host.url)
            global host_cycle
            host_cycle = itertools.cycle(ollama_hosts)
    return {"status": "registered", "hosts": ollama_hosts}

@app.post("/unregister")
def unregister_host(host: Host):
    with lock:
        if host.url in ollama_hosts:
            ollama_hosts.remove(host.url)
            global host_cycle
            host_cycle = itertools.cycle(ollama_hosts)
    return {"status": "unregistered", "hosts": ollama_hosts}

@app.get("/hosts")
def list_hosts():
    return {"hosts": ollama_hosts}

def forward_request(method: str, path: str, data: dict, host: str):
    url = f"{host}/{path}"
    try:
        if method == "GET":
            response = requests.get(url, json=data, stream=True)
        elif method == "POST":
            response = requests.post(url, json=data, stream=True)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Host {host} failed: {str(e)}")

def get_next_host():
    with lock:
        if not ollama_hosts:
            raise HTTPException(status_code=503, detail="No Ollama hosts registered")
        return next(host_cycle)

# Proxy for Ollama API endpoints (e.g., /api/generate, /api/chat)
@app.api_route("/{path:path}", methods=["GET", "POST"])
async def proxy(request: Request, path: str):
    data = await request.json() if request.method == "POST" else {}
    host = get_next_host()
    try:
        response = forward_request(request.method, path, data, host)
        def stream_gen():
            for chunk in response.iter_content(chunk_size=1024):
                yield chunk
        return StreamingResponse(stream_gen(), media_type=response.headers.get("Content-Type", "application/json"), status_code=response.status_code)
    except HTTPException:
        # Fallback to next host on failure
        host = get_next_host()
        response = forward_request(request.method, path, data, host)
        def stream_gen():
            for chunk in response.iter_content(chunk_size=1024):
                yield chunk
        return StreamingResponse(stream_gen(), media_type=response.headers.get("Content-Type", "application/json"), status_code=response.status_code)

# Admin: Pull model on all hosts
@app.post("/admin/pull")
def admin_pull(model: ModelCommand):
    results = {}
    with lock:
        for host in ollama_hosts:
            try:
                response = requests.post(f"{host}/api/pull", json={"name": model.model})
                response.raise_for_status()
                results[host] = "success"
            except requests.RequestException as e:
                results[host] = f"failed: {str(e)}"
    return {"results": results}

# Admin: List models on all hosts
@app.get("/admin/list_models")
def admin_list_models():
    results = {}
    with lock:
        for host in ollama_hosts:
            try:
                response = requests.get(f"{host}/api/tags")
                response.raise_for_status()
                results[host] = response.json()
            except requests.RequestException as e:
                results[host] = f"failed: {str(e)}"
    return {"results": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)