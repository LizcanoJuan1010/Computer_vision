# VIGIAS-IA System Walkthrough

## 📌 Sistema con Multi-Tenancy

Este documento explica en detalle cómo funciona el sistema VIGIAS-IA después de la implementación de multi-tenancy.

---

## 🏗️ Arquitectura General

```mermaid
flowchart TB
    subgraph Cameras["📹 Cámaras Hikvision"]
        CAM701[cam_701]
        CAM1001[cam_1001]
        CAM1301[cam_1301]
        CAM2201[cam_2201]
        CAM2701[cam_2701]
    end

    subgraph Docker["🐳 Docker Compose"]
        subgraph Ingest["Ingest Service (Go) :8081"]
            RTSP[RTSP Reader]
            MOG2[Motion Filter]
            PUBLISH[NATS Publisher]
        end
        
        NATS["NATS JetStream :4223"]
        REDIS["Redis Cache :6380"]
        POSTGRES["PostgreSQL :5436"]
        
        subgraph Router["Router API (FastAPI) :8003"]
            API[REST Endpoints]
            WS[WebSocket]
            DISPATCH[Dispatcher]
        end
    end
    
    subgraph Inference["🤖 Inference (Conda) :5000"]
        YOLO["YOLO v8 (CUDA)"]
        FACE["InsightFace"]
        LPR["LPR Model"]
        SPATIAL["Spatial Analytics"]
        MJPEG["MJPEG Stream"]
    end

    CAM701 & CAM1001 & CAM1301 & CAM2201 & CAM2701 -->|RTSP| RTSP
    RTSP --> MOG2 --> PUBLISH
    PUBLISH -->|org.vigias-local.zone.zona-default.camera.X.frame| NATS
    NATS --> Inference
    YOLO --> FACE --> LPR --> SPATIAL --> MJPEG
    SPATIAL -->|org.vigias-local.events.alarm| NATS
    NATS --> WS
    Router --> REDIS
    Router --> POSTGRES
```

---

## 📡 Flujo de Datos Paso a Paso

### 1️⃣ Ingesta de Video (Ingest Service)

**Ubicación:** `/home/logisticos-two/dev/Proyect_Computer_Vision/ingest/`

**Tecnología:** Go (compilado en Docker)

```mermaid
sequenceDiagram
    participant Cam as Cámara RTSP
    participant FFmpeg as FFmpeg Decoder
    participant MOG2 as Motion Filter
    participant Pub as NATS Publisher

    Cam->>FFmpeg: Stream H.264
    FFmpeg->>FFmpeg: Decode to RGB
    FFmpeg->>MOG2: Frame 640x360
    MOG2->>MOG2: Detect Motion
    alt Motion Detected
        MOG2->>Pub: Encode JPEG
        Pub->>Pub: Build Subject
        Note over Pub: org.{org_slug}.zone.{zone_slug}.camera.{id}.frame
        Pub-->>NATS: Publish Frame
    end
```

**Configuración:** `cameras.json`
```json
{
  "id": "cam_701",
  "org_slug": "vigias-local",    // ← Multi-tenancy
  "zone_slug": "zona-default",   // ← Multi-tenancy
  "url": "rtsp://{USER}:{PASS}@{IP}:{PORT_RTSP}/Streaming/Channels/701"
}
```

---

### 2️⃣ Mensajería (NATS)

**Puerto:** 4223

**Subjects Multi-Tenancy:**
| Tipo | Subject Pattern |
|------|-----------------|
| Frames | `org.{org}.zone.{zone}.camera.{id}.frame` |
| Alarms | `org.{org}.events.alarm` |
| Config | `org.{org}.zone.{zone}.camera.{id}.config` |

**Ejemplo Real:**
```
org.vigias-local.zone.zona-default.camera.cam_701.frame
```

---

### 3️⃣ Procesamiento IA (Inference Service)

**Ubicación:** `/home/logisticos-two/dev/Proyect_Computer_Vision/inference/`

**Entorno:** Miniconda3 (`vigias-ia`)

#### Activación del Entorno

```bash
source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia
```

#### Ejecución

```bash
cd /home/logisticos-two/dev/Proyect_Computer_Vision
python -c "from inference.main import run; import asyncio; asyncio.run(run())"
```

#### Pipeline de Modelos

```mermaid
flowchart LR
    subgraph Input["Frame de NATS"]
        FRAME[JPEG 640x360]
    end
    
    subgraph Models["Modelos GPU"]
        YOLO["YOLO v8n<br/>cuda:0 FP16"]
        FACE["InsightFace<br/>buffalo_l"]
        LPR["LPR<br/>OCR"]
    end
    
    subgraph Analytics["Spatial Analytics"]
        ZONE["PolygonZone"]
        LINE["LineCrossing"]
        DEBOUND["Debouncing"]
    end
    
    subgraph Output["Salida"]
        ALARM["Alarma NATS"]
        STREAM["MJPEG Stream"]
        DB["PostgreSQL"]
    end

    FRAME --> YOLO
    YOLO -->|Detections| FACE
    YOLO -->|Detections| LPR
    YOLO -->|Detections| ZONE
    YOLO -->|Detections| LINE
    ZONE --> DEBOUND
    LINE --> DEBOUND
    DEBOUND -->|Si nuevo evento| ALARM
    DEBOUND -->|Si nuevo evento| DB
    FACE --> STREAM
    LPR --> STREAM
    ZONE --> STREAM
```

#### Configuración GPU

```python
# inference/models/yolo.py
self.model = pt_model.to('cuda')  # GPU
result = self.model(frame, half=True)  # FP16
```

---

### 4️⃣ API Backend (Router Service)

**Puerto:** 8003

**Tecnología:** FastAPI + SQLAlchemy Async

#### Endpoints Multi-Tenancy

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/orgs` | Listar organizaciones |
| POST | `/api/v1/orgs` | Crear organización |
| GET | `/api/v1/orgs/{slug}/zones` | Listar zonas |
| POST | `/api/v1/orgs/{slug}/zones` | Crear zona |
| GET | `/api/v1/cameras` | Listar cámaras (legacy) |
| POST | `/admin/cache/warmup` | Calentar cache Redis |
| GET | `/health` | Health check avanzado |

#### Cache Multi-Tenancy (Redis)

```python
# Nueva clave
config:org:vigias-local:zone:zona-default:camera:cam_701

# Clave legacy (backward compatible)
config:camera:cam_701
```

---

### 5️⃣ Base de Datos (PostgreSQL)

**Puerto:** 5436

#### Tablas Multi-Tenancy

```mermaid
erDiagram
    organizations ||--o{ org_zones : has
    org_zones ||--o{ cameras : contains
    cameras ||--o{ camera_ai_configs : has
    cameras ||--o{ events : generates
    
    organizations {
        uuid id PK
        varchar slug UK
        varchar name
        boolean is_managed
    }
    
    org_zones {
        uuid id PK
        uuid organization_id FK
        varchar slug
        varchar name
    }
    
    cameras {
        uuid id PK
        uuid zone_id FK
        varchar name
        text rtsp_url
    }
```

#### Estado Actual

| Tabla | Registros |
|-------|-----------|
| organizations | 2 |
| org_zones | 2 |
| cameras | 2* |
| events | 150+ |

*Nota: Faltan 3 cámaras en BD, existen en cameras.json

---

### 6️⃣ Streaming al Frontend

**Endpoint Inference:** `http://localhost:5000/debug/{camera_id}/mjpeg`

```mermaid
sequenceDiagram
    participant Browser as Navegador
    participant Inference as Inference:5000
    participant Store as Frame Store

    Browser->>Inference: GET /debug/cam_701/mjpeg
    Inference->>Inference: Set Content-Type: multipart/x-mixed-replace
    loop Cada Frame
        Store->>Inference: Frame anotado
        Inference->>Browser: --frame\r\nContent-Type: image/jpeg\r\n{bytes}
    end
```

---

## 🔧 Comandos de Operación

### Levantar Sistema Completo

```bash
# 1. Docker (NATS, Redis, Postgres, Router, Ingest)
cd /home/logisticos-two/dev/Proyect_Computer_Vision
docker-compose up -d --build

# 2. Inference (GPU)
nohup bash -c 'source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia && \
cd /home/logisticos-two/dev/Proyect_Computer_Vision && \
python -c "from inference.main import run; import asyncio; asyncio.run(run())"' \
> /tmp/inference.log 2>&1 &
```

### Health Check

```bash
# Router
curl http://localhost:8003/health

# Inference
curl -s http://localhost:5000/debug/cam_701/mjpeg -o /dev/null -w "%{http_code}"
```

### Cache Warmup

```bash
curl -X POST http://localhost:8003/admin/cache/warmup
```

---

## 📊 Resumen de Puertos

| Puerto | Servicio | Stack |
|--------|----------|-------|
| 4223 | NATS | Docker |
| 5436 | PostgreSQL | Docker |
| 6380 | Redis | Docker |
| 8003 | Router API | Docker (FastAPI) |
| 8081 | Ingest | Docker (Go) |
| 5000 | Inference | Conda (Python+CUDA) |

---

## 🔗 URLs de Streams

| Cámara | URL Stream con IA |
|--------|-------------------|
| cam_701 | http://localhost:5000/debug/cam_701/mjpeg |
| cam_1001 | http://localhost:5000/debug/cam_1001/mjpeg |
| cam_1301 | http://localhost:5000/debug/cam_1301/mjpeg |
| cam_2201 | http://localhost:5000/debug/cam_2201/mjpeg |
| cam_2701 | http://localhost:5000/debug/cam_2701/mjpeg |
