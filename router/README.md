# AI Router & Orchestrator 🧠⚡

The **AI Router** is the central nervous system of the VIGIAS-IA platform. It acts as a high-performance traffic dispatcher that decouples video ingestion from AI inference.

## 🚀 Why this Microservice?

In a scalable computer vision system, you cannot simply broadcast every video frame to every AI model. That would saturate GPUs and network bandwidth instantly.

The Router solves this by:
1.  **Decoupling**: Ingestion services don't know about AI models. They just send frames.
2.  **Zero-Copy Routing**: It inspects packet headers and routes the payload **without ever decoding the image**. This adds <1ms latency.
3.  **Dynamic Orchestration**: You can enable/disable AI models (YOLO, Face, LPR) for specific cameras in real-time without restarting services.

## 🏗️ Architecture

### Data Flow
1.  **Ingest**: Publishes raw frames to `camera.{id}.frame`.
2.  **Router**:
    *   Subscribes to `camera.*.frame`.
    *   Extracts `{id}` from the subject.
    *   Consults **Tiered Cache** (L1 Memory -> L2 Redis) to see which services are active for this camera.
    *   **Fans-out** the message to `work.{service}` (e.g., `work.security`, `work.lpr`).
3.  **Inference**: Workers listen to `work.{service}` and process the frame.

### Tiered Caching Strategy
*   **L1 (Memory)**: `TTLCache`. Sub-microsecond access. Stores config for 60s.
*   **L2 (Redis)**: Persistent configuration store. Shared across Router replicas.

## 📂 Project Structure

```text
router/
├── app/
│   ├── core/           # Configuration & Settings
│   ├── services/       # Business Logic (Dispatcher, Cache)
│   ├── api/            # FastAPI Endpoints
│   └── main.py         # Application Entrypoint
├── scripts/            # Utility scripts (e.g., database seeding)
├── Dockerfile          # Python 3.11 optimized image
└── requirements.txt    # High-performance dependencies (uvloop, orjson)
```

## ⚙️ Configuration

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `NATS_URL` | `nats://localhost:4222` | NATS Server URL |
| `REDIS_HOST` | `localhost` | Redis Host (L2 Cache) |
| `REDIS_PORT` | `6379` | Redis Port |
| `L1_TTL` | `60` | L1 Cache Time-To-Live (seconds) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

## 🔌 API Endpoints (Management)

The Router exposes a lightweight REST API for orchestration:

*   `GET /health`: Kubernetes Liveness probe.
*   `POST /config/{camera_id}`: Update active services for a camera (Updates Redis + Purges L1).
    *   Body: `["security", "lpr"]`
*   `GET /debug/routes/{camera_id}`: View current routing logic for a camera.

## 🛠️ How to Run

### Docker (Recommended)
The service is included in the main `docker-compose.yml`.

```bash
# Start the entire stack
./start_system.sh
```

### Local Development
```bash
cd router
pip install -r requirements.txt
export REDIS_HOST=localhost
export NATS_URL=nats://localhost:4222
uvicorn app.main:app --reload
```
