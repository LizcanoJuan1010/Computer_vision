# VIGIAS-IA Ingestion Service

This service is the entry point ("The Porter") for the VIGIAS-IA platform. It captures video streams, performs motion gating, and publishes frames to NATS.

## Features
- **Concurrent Pipeline**: Uses Go routines for Capture, Process, and Publish.
- **Motion Gating (MOG2)**: Filters out static frames using Gaussian Mixture-based Background Subtraction.
- **RTSP Reconnection**: Automatically retries connections with backoff.
- **Metrics**: Exposes Prometheus-compatible metrics on port 8080.
- **Configurable**: Fully controlled via Environment Variables.

## Directory Structure
```
ingest/
├── cmd/
│   └── server/         # Entry point (main.go)
├── internal/
│   ├── config/         # Configuration loading
│   ├── pipeline/       # Core logic (Capture, Process, Publish)
```

## Configuration
Set these environment variables to configure the service:

| Variable | Default | Description |
|----------|---------|-------------|
| `VIDEO_SOURCE` | `rtsp://user:pass@ip:554/stream` | RTSP URL (e.g., `rtsp://user:pass@ip:554/stream`) |
| `NATS_URL` | `nats://localhost:4222` | NATS Server URL |
| `CAMERA_ID` | `001` | Unique ID for the camera (used in NATS topic) |
| `TARGET_FPS` | `5.0` | FPS limit for ingestion |
| `RESIZE_WIDTH` | `640` | Width to resize frames to |
| `RESIZE_HEIGHT` | `360` | Height to resize frames to |
| `METRICS_PORT` | `8080` | Port for `/metrics` endpoint |

## Running
### Local (Development)
```bash
go run cmd/server/main.go
```

### Docker (Recommended)
Build the image (ensure you have the Dockerfile):
```bash
docker build -t vigias-ingest .
```
Run with env vars:
```bash
docker run -e VIDEO_SOURCE="rtsp://..." -e CAMERA_ID="cam01" --network host vigias-ingest
```
