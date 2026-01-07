# 🧪 Guía de Operación y Pruebas: VIGIAS-IA

## Versión: Multi-Tenancy
**Actualizado:** 2025-12-19

---

## 📂 Directorio Base

```bash
cd /home/logisticos-two/dev/Proyect_Computer_Vision
```

---

## 🚀 Levantar el Sistema

### 1. Docker Compose (NATS, Redis, Postgres, Router, Ingest)

```bash
# Con rebuild
docker-compose up -d --build

# Sin rebuild (más rápido)
docker-compose up -d

# Ver logs en vivo
docker-compose logs -f
```

### 2. Inference Service (GPU - Miniconda)

```bash
# Foreground (para debug)
source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia
cd /home/logisticos-two/dev/Proyect_Computer_Vision
python -c "from inference.main import run; import asyncio; asyncio.run(run())"

# Background (producción)
nohup bash -c 'source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia && \
cd /home/logisticos-two/dev/Proyect_Computer_Vision && \
python -c "from inference.main import run; import asyncio; asyncio.run(run())"' \
> /tmp/inference.log 2>&1 &
```

### 3. Verificar que todo está corriendo

```bash
docker-compose ps
ps aux | grep inference
```

---

## 🛑 Detener el Sistema

```bash
# Docker
docker-compose down

# Inference
pkill -f "inference.main"

# Reset completo (⚠️ borra datos)
docker-compose down -v
```

---

## 🔄 Reiniciar

```bash
# Docker
docker-compose restart

# Solo un servicio
docker-compose restart router
docker-compose restart ingest

# Inference
pkill -f "inference.main"
# Luego volver a levantar con los comandos anteriores
```

---

## ❤️ Health Checks

### Router API (Avanzado)

```bash
curl http://localhost:8003/health | jq
```

**Respuesta esperada:**
```json
{
  "status": "ok",
  "services": {
    "database": "ok",
    "redis": "ok",
    "nats": "ok"
  },
  "cache": {
    "l1_size": 5,
    "l1_max": 256,
    "l1_ttl": 5
  }
}
```

### Todos los servicios

```bash
# NATS
curl http://localhost:8223/healthz

# Redis
docker-compose exec redis redis-cli ping
# Esperado: PONG

# PostgreSQL
docker-compose exec postgres pg_isready -U user -d vigias
# Esperado: accepting connections

# Inference (stream test)
curl -s http://localhost:5000/debug/cam_701/mjpeg -o /dev/null --max-time 2 -w "%{http_code}\n"
# Esperado: 200

# GPU
nvidia-smi
```

---

## 🌐 Endpoints API

### Swagger UI
**URL:** http://localhost:8003/docs

### Multi-Tenancy (Nuevo)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/orgs` | Listar organizaciones |
| POST | `/api/v1/orgs` | Crear organización |
| GET | `/api/v1/orgs/{slug}` | Obtener organización |
| GET | `/api/v1/orgs/{slug}/zones` | Listar zonas |
| POST | `/api/v1/orgs/{slug}/zones` | Crear zona |
| POST | `/admin/cache/warmup` | Calentar cache Redis |

### Cámaras

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/cameras` | Listar cámaras |
| POST | `/api/v1/cameras` | Crear cámara |
| GET | `/api/v1/cameras/{id}` | Obtener cámara |
| GET | `/api/v1/cameras/{id}/zones` | Zonas AI de cámara |
| POST | `/api/v1/cameras/{id}/zones` | Crear zona AI |

### Streaming

| Endpoint | Descripción |
|----------|-------------|
| `http://localhost:5000/debug/cam_701/mjpeg` | Stream cam_701 con IA |
| `http://localhost:5000/debug/cam_1001/mjpeg` | Stream cam_1001 con IA |
| `http://localhost:5000/debug/cam_1301/mjpeg` | Stream cam_1301 con IA |
| `http://localhost:5000/debug/cam_2201/mjpeg` | Stream cam_2201 con IA |
| `http://localhost:5000/debug/cam_2701/mjpeg` | Stream cam_2701 con IA |

### WebSocket

```bash
# Instalar wscat
npm install -g wscat

# Conectar
wscat -c ws://localhost:8003/ws/notifications
```

---

## 🧪 Pruebas de Multi-Tenancy

### 1. Listar Organizaciones

```bash
curl http://localhost:8003/api/v1/orgs | jq
```

**Esperado:**
```json
[
  {
    "id": "771247e7-ed96-49c2-8d64-a939f99542a1",
    "slug": "vigias-local",
    "name": "Vigias Local",
    "is_managed": false
  }
]
```

### 2. Listar Zonas de una Organización

```bash
curl http://localhost:8003/api/v1/orgs/vigias-local/zones | jq
```

### 3. Cache Warmup

```bash
curl -X POST http://localhost:8003/admin/cache/warmup | jq
```

**Esperado:**
```json
{
  "status": "completed",
  "cameras_warmed": 2,
  "total_cameras": 2,
  "errors": []
}
```

### 4. Verificar Cache Redis

```bash
docker-compose exec redis redis-cli KEYS "config:*"
```

**Esperado:**
```
1) "config:org:vigias-local:zone:zona-default:camera:1440355a-..."
2) "config:org:vigias-local:zone:zona-default:camera:cc9a1778-..."
```

---

## 🧪 Pruebas de Funcionalidad

### 1. Registrar Rostro

```bash
curl -X POST "http://localhost:8003/api/v1/faces/" \
  -F "name=Test_User" \
  -F "file=@/path/to/photo.jpg"
```

### 2. Listar Rostros

```bash
curl http://localhost:8003/api/v1/faces/
```

### 3. Ver Alarmas

```bash
curl http://localhost:8003/api/v1/alarms/ | jq
```

### 4. Resumen del Sistema

```bash
curl http://localhost:8003/api/v1/system/summary | jq
```

**Esperado:**
```json
{
  "cameras": 2,
  "events": 150,
  "users": 0,
  "roles": 0
}
```

---

## 📊 Monitoreo

### Logs Docker

```bash
# Todos
docker-compose logs -f

# Solo Router
docker-compose logs -f router

# Solo Ingest
docker-compose logs -f ingest

# Últimas 50 líneas
docker-compose logs --tail=50 router
```

### Logs Inference

```bash
tail -f /tmp/inference.log
```

### Recursos

```bash
# Docker
docker stats

# GPU
watch -n 1 nvidia-smi
```

---

## 🔧 Troubleshooting

### Inference no inicia

```bash
# Verificar CUDA
nvidia-smi

# Verificar entorno
conda activate vigias-ia
python -c "import torch; print(torch.cuda.is_available())"
```

### Cámaras no conectan

```bash
# Verificar .env
cat .env

# Verificar cameras.json
cat ingest/cameras.json | jq '.[].id'

# Ver errores Ingest
docker-compose logs ingest | grep -i error
```

### BD sin tablas

```bash
docker-compose exec router python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.models import Base
from app.core.config import settings

async def init():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Tables created!')
    await engine.dispose()

asyncio.run(init())
"
```

### Reset Completo

```bash
docker-compose down -v
docker-compose up --build -d
```

---

## 📋 Resumen de Puertos

| Puerto | Servicio | Descripción |
|--------|----------|-------------|
| 4223 | NATS | Message broker |
| 5436 | PostgreSQL | Base de datos |
| 6380 | Redis | Cache L2 |
| 8003 | Router | API REST + WebSocket |
| 8081 | Ingest | Métricas Go |
| 5000 | Inference | Stream MJPEG + IA |
| 8223 | NATS HTTP | Monitoring NATS |

---

## 🔄 Script de Inicio Rápido

```bash
#!/bin/bash
cd /home/logisticos-two/dev/Proyect_Computer_Vision

echo "1. Levantando Docker..."
docker-compose up -d --build

echo "2. Esperando servicios..."
sleep 10

echo "3. Verificando salud..."
curl -s http://localhost:8003/health | jq

echo "4. Levantando Inference..."
nohup bash -c 'source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia && \
cd /home/logisticos-two/dev/Proyect_Computer_Vision && \
python -c "from inference.main import run; import asyncio; asyncio.run(run())"' \
> /tmp/inference.log 2>&1 &

echo "5. Esperando Inference..."
sleep 15

echo "6. Calentando cache..."
curl -X POST http://localhost:8003/admin/cache/warmup | jq

echo "✅ Sistema listo!"
echo "Stream: http://localhost:5000/debug/cam_701/mjpeg"
echo "API: http://localhost:8003/docs"
```
