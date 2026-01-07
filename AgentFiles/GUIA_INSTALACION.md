# VIGIAS-IA - GUÍA DE INSTALACIÓN Y DESPLIEGUE

**Versión**: 2.0.0-beta (Sprint 1 Day 1)
**Fecha**: 2025-12-26
**Sistema**: Ubuntu 20.04+ con GPU NVIDIA

---

## 📋 ÍNDICE

1. [Requisitos del Sistema](#requisitos-del-sistema)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Instalación Paso a Paso](#instalación-paso-a-paso)
4. [Verificación del Sistema](#verificación-del-sistema)
5. [Solución de Problemas](#solución-de-problemas)
6. [Comandos Útiles](#comandos-útiles)

---

## 🖥️ REQUISITOS DEL SISTEMA

### Hardware Mínimo
- **CPU**: 8 cores (Intel i7 o AMD Ryzen 7)
- **RAM**: 16 GB
- **GPU**: NVIDIA GTX 1660 o superior (6GB VRAM)
- **Disco**: 500 GB SSD
- **Red**: 1 Gbps

### Hardware Recomendado (Producción)
- **CPU**: 16 cores (Intel i9 o AMD Ryzen 9)
- **RAM**: 32 GB
- **GPU**: NVIDIA RTX 3060 o superior (12GB VRAM)
- **Disco**: 1 TB NVMe SSD
- **Red**: 10 Gbps

### Software Requerido
```bash
# Sistema Operativo
Ubuntu 22.04 LTS (recomendado)

# Docker
Docker Engine 24.0+
Docker Compose 2.20+

# NVIDIA Drivers
Driver 535+ (para CUDA 12.2)
NVIDIA Container Toolkit

# Python (solo para inference service)
Python 3.11+
Miniconda3 o Anaconda
```

---

## 🏗️ ARQUITECTURA DEL SISTEMA

```
┌─────────────────────────────────────────────────────────────────┐
│                      VIGIAS-IA v2.0                             │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌─────────────┐
│   RTSP Cameras   │─────▶│  Ingest Service  │─────▶│    NATS     │
│  (HIKVision)     │      │   (Go/FFmpeg)    │      │ (Messaging) │
└──────────────────┘      └──────────────────┘      └─────────────┘
                                                            │
                                                            ▼
┌──────────────────────────────────────────────────────────────────┐
│               INFERENCE SERVICE (Python + GPU)                   │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐            │
│  │   YOLOv11   │  │ InsightFace │  │  LPR Model   │            │
│  └─────────────┘  └─────────────┘  └──────────────┘            │
│  ┌──────────────────────────────────────────────────┐           │
│  │        Face Cache LFU (L1: Memory + L2: Redis)   │           │
│  └──────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────┘
                          │                     │
                          ▼                     ▼
                   ┌─────────────┐      ┌─────────────┐
                   │  PostgreSQL │      │    Redis    │
                   │  (pgvector) │      │  (Cache L2) │
                   └─────────────┘      └─────────────┘
                          ▲
                          │
┌──────────────────────────────────────────────────────────────────┐
│                    ROUTER API (FastAPI)                          │
│  Endpoints: Events, Faces, Cameras, Notifications, Zones        │
└──────────────────────────────────────────────────────────────────┘
                          ▲
                          │
                   ┌─────────────┐
                   │  Frontend   │
                   │  (Cliente)  │
                   └─────────────┘
```

### Puertos Utilizados

| Servicio | Puerto Host | Puerto Container | Descripción |
|----------|-------------|------------------|-------------|
| **Router API** | 8003 | 8000 | API REST principal |
| **Inference Debug Stream** | 5000 | 5000 | Stream MJPEG de debug |
| **PostgreSQL (Vision)** | 5436 | 5432 | Base de datos Vision AI |
| **Redis (Vision)** | 6380 | 6379 | Cache L2 + Config |
| **NATS** | 4223 | 4222 | Messaging NATS JetStream |
| API Gateway | 8080 | 8080 | Spring Cloud Gateway |
| Eureka | 8761 | 8761 | Service Discovery |
| Keycloak | 8086 | 8080 | Identity Management |

---

## 🚀 INSTALACIÓN PASO A PASO

### 1. Clonar Repositorio

```bash
cd /home/logisticos-two/dev
git clone <repository-url> Proyect_Computer_Vision
cd Proyect_Computer_Vision
git checkout feature/production-ready-v2.0
```

### 2. Instalar NVIDIA Drivers y Container Toolkit

```bash
# Instalar NVIDIA Driver
sudo apt update
sudo apt install -y nvidia-driver-535
sudo reboot

# Verificar instalación
nvidia-smi

# Instalar NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# Verificar
docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
```

### 3. Configurar Variables de Entorno

```bash
# Crear archivo .env en el directorio raíz
cd /home/logisticos-two/dev
cp .env.example .env

# Editar .env con tus credenciales
nano .env
```

**Contenido de `.env`:**
```bash
# Database
POSTGRES_USER=user
POSTGRES_PASSWORD=password
POSTGRES_DB=vigias

# Vision AI Database
VISION_DB_USER=vision_user
VISION_DB_PASSWORD=vision_pass
VISION_DB_NAME=vigias_vision

# Redis
REDIS_PASSWORD=redis_password

# Keycloak
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin_password

# Cameras (HIKVision)
HIK_USER=admin
HIK_PASS=camera_password
HIK_IP=192.168.1.100
```

### 4. Levantar Servicios Docker

```bash
cd /home/logisticos-two/dev

# Levantar servicios en orden
# 1. Bases de datos
docker-compose up -d postgres vision-postgres keycloak-db maps-postgres

# Esperar 30 segundos
sleep 30

# 2. Infraestructura
docker-compose up -d config-server eureka-server keycloak vision-nats vision-redis

# Esperar 30 segundos
sleep 30

# 3. Microservicios
docker-compose up -d api-gateway config-ms identity-ms organization-ms ops-ms

# 4. Servicios de Vision AI
docker-compose up -d vision-router maps-api

# Esperar que vision-router esté saludable
sleep 20

# 5. Ingest (captura de cámaras)
docker-compose up -d vision-ingest
```

### 5. Ejecutar Migraciones de Base de Datos

```bash
cd /home/logisticos-two/dev/Proyect_Computer_Vision

# Migration 001: Schema inicial (ya ejecutado)
docker exec -i dev_vision-postgres_1 psql -U vision_user -d vigias_vision < database/migration_001_initial_schema.sql

# Migration 002: Multi-tenancy (ya ejecutado)
docker exec -i dev_vision-postgres_1 psql -U vision_user -d vigias_vision < database/migration_002_multitenancy.sql

# Migration 003: Face embeddings con pgvector
docker exec -i dev_vision-postgres_1 psql -U vision_user -d vigias_vision < database/migration_003_add_face_embeddings.sql

# Migration 004: Hybrid blacklist model
docker exec -i dev_vision-postgres_1 psql -U vision_user -d vigias_vision < database/migration_004_face_improvements.sql
```

### 6. Instalar Miniconda y Dependencias Python

```bash
# Instalar Miniconda (si no está instalado)
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -p $HOME/miniconda3
source $HOME/miniconda3/bin/activate

# Crear entorno virtual
cd /home/logisticos-two/dev/Proyect_Computer_Vision
conda create -n vigias python=3.11 -y
conda activate vigias

# Instalar PyTorch con CUDA
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Instalar dependencias
pip install -r inference/requirements.txt

# Verificar instalación
python -c "import torch; print(f'PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
```

### 7. Iniciar Servicio de Inferencia

```bash
cd /home/logisticos-two/dev/Proyect_Computer_Vision
conda activate vigias

# Iniciar en background
nohup python -u -m inference.main > /tmp/inference.log 2>&1 &

# Ver logs en tiempo real
tail -f /tmp/inference.log
```

**Salida esperada:**
```
uvloop installed.
Connecting to DB: dbname=vigias_vision user=vision_user password=vision_pass host=localhost port=5436
✅ Extensions verified. Schema managed by schema.sql (UUIDs)
Loading faces into memory...
Loaded 0 faces.
Database connected, schema initialized, and faces loaded.
DB Worker started.
Loading YOLO model: yolo11n.pt...
Loaded YOLO model (PyTorch) on cuda:0
Loading InsightFace model: buffalo_l...
InsightFace initialized.
Loading LPR model: placas_colombia.pt...
Loaded LPR model on cuda:0
🔄 Initializing FaceCacheLFU (Hybrid L1+L2)...
✅ Redis connection established: redis://localhost:6380/0
ℹ️  No global blacklist entries found
✅ FaceCacheLFU initialized (L1 capacity: 1000)
Connecting to NATS at nats://localhost:4223...
Subscribing to work.security...
✅ Subscribed to cache invalidation events (events.face.*)
Listening for frames... Press Ctrl+C to exit.
Batch processor started.
Debug Stream Server running on http://0.0.0.0:5000
```

---

## ✅ VERIFICACIÓN DEL SISTEMA

### 1. Verificar Servicios Docker

```bash
docker-compose ps
```

**Servicios esperados (healthy):**
```
dev-api-gateway-1         Up (healthy)
dev-config-ms-1           Up (healthy)
dev-config-server-1       Up (healthy)
dev-eureka-server-1       Up (healthy)
dev-identity-ms-1         Up (healthy)
dev-keycloak-1            Up
dev-organization-ms-1     Up (healthy)
dev-ops-ms-1              Up (healthy)
dev-vision-router-1       Up
dev-vision-postgres-1     Up (healthy)
dev-vision-redis-1        Up (healthy)
dev-vision-nats-1         Up (healthy)
dev-vision-ingest-1       Up
```

### 2. Verificar Puertos Abiertos

```bash
netstat -tulpn | grep -E "(8003|5000|5436|6380|4223)"
```

**Salida esperada:**
```
tcp6  0  0  :::8003   :::*   LISTEN   (vision-router)
tcp6  0  0  :::5000   :::*   LISTEN   (inference)
tcp6  0  0  :::5436   :::*   LISTEN   (vision-postgres)
tcp6  0  0  :::6380   :::*   LISTEN   (vision-redis)
tcp6  0  0  :::4223   :::*   LISTEN   (vision-nats)
```

### 3. Test de API Router

```bash
# Health check
curl http://localhost:8003/health

# Respuesta esperada:
{
  "status": "healthy",
  "timestamp": "2025-12-26T18:30:00Z",
  "services": {
    "database": "connected",
    "nats": "connected",
    "redis": "connected"
  }
}
```

### 4. Test de Inference Service

```bash
# Verificar proceso corriendo
ps aux | grep "python.*inference.main"

# Ver stream de debug (abre en navegador)
# http://localhost:5000/debug/cam_01/mjpeg
```

### 5. Test de Base de Datos

```bash
# Conectar a PostgreSQL
docker exec -it dev_vision-postgres_1 psql -U vision_user -d vigias_vision

# Verificar extensiones
vigias_vision=# \dx
                                     List of installed extensions
  Name   | Version |   Schema   |                         Description
---------+---------+------------+-------------------------------------------------------------
 plpgsql | 1.0     | pg_catalog | PL/pgSQL procedural language
 uuid-ossp | 1.1   | public     | generate universally unique identifiers (UUIDs)
 vector  | 0.5.1   | public     | vector data type and ivfflat access method

# Verificar tablas
vigias_vision=# \dt
                    List of relations
 Schema |            Name            | Type  |    Owner
--------+----------------------------+-------+-------------
 public | blacklist_sharing_log      | table | vision_user
 public | camera_ai_configs          | table | vision_user
 public | cameras                    | table | vision_user
 public | events                     | table | vision_user
 public | faces                      | table | vision_user
 public | org_zones                  | table | vision_user
 public | organizations              | table | vision_user
 public | temporary_whitelists       | table | vision_user

# Salir
\q
```

---

## 🔧 SOLUCIÓN DE PROBLEMAS

### Problema: Puerto 8003 (Router API) no responde

**Diagnóstico:**
```bash
# Ver logs de vision-router
docker logs dev-vision-router-1 --tail 100

# Ver estado del contenedor
docker inspect dev-vision-router-1 | grep -A 10 "State"
```

**Soluciones:**

1. **Restart del servicio:**
```bash
docker-compose restart vision-router
docker logs -f dev-vision-router-1
```

2. **Rebuild si hay cambios en código:**
```bash
docker-compose stop vision-router
docker-compose build --no-cache vision-router
docker-compose up -d vision-router
```

3. **Verificar dependencias:**
```bash
# Asegurarse que postgres, nats y redis estén saludables
docker-compose ps | grep -E "(postgres|nats|redis)"
```

### Problema: Inference Service no conecta a base de datos

**Error:**
```
connection to server at "localhost" (127.0.0.1), port 5436 failed: Connection refused
```

**Solución:**
```bash
# 1. Verificar que el puerto esté expuesto
docker ps | grep vision-postgres
# Debe mostrar: 0.0.0.0:5436->5432/tcp

# 2. Si no está expuesto, revisar docker-compose.yml
grep -A 5 "vision-postgres:" docker-compose.yml

# 3. Recrear contenedor con puertos
docker-compose stop vision-postgres
docker-compose rm -f vision-postgres
docker-compose up -d vision-postgres
```

### Problema: Face Cache no inicializa (AttributeError: 'Database' object has no attribute 'fetch_all')

**Causa:** El cache intentaba usar un método async que no existe en Database.

**Solución:** Ya corregido en `face_cache_lfu.py` usando `asyncio.to_thread()`.

**Verificar fix:**
```bash
grep -A 5 "asyncio.to_thread" inference/cache/face_cache_lfu.py
```

### Problema: GPU no detectada

**Diagnóstico:**
```bash
# Verificar driver
nvidia-smi

# Verificar en Python
python -c "import torch; print(torch.cuda.is_available())"
```

**Soluciones:**

1. **Reinstalar NVIDIA drivers:**
```bash
sudo apt purge nvidia-*
sudo apt install nvidia-driver-535
sudo reboot
```

2. **Reinstalar PyTorch con CUDA:**
```bash
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

### Problema: Cámaras no conectan (Ingest)

**Diagnóstico:**
```bash
docker logs dev-vision-ingest-1 --tail 50
```

**Soluciones:**

1. **Verificar credenciales en .env:**
```bash
grep -E "(HIK_USER|HIK_PASS|HIK_IP)" .env
```

2. **Ping a la cámara:**
```bash
ping 192.168.1.100
```

3. **Test RTSP manual:**
```bash
ffmpeg -rtsp_transport tcp -i "rtsp://admin:password@192.168.1.100:554/Streaming/Channels/101" -t 5 test.mp4
```

---

## 📝 COMANDOS ÚTILES

### Docker

```bash
# Ver logs de todos los servicios
docker-compose logs -f

# Ver logs de un servicio específico
docker logs -f dev-vision-router-1

# Restart todos los servicios
docker-compose restart

# Stop y eliminar todos los contenedores
docker-compose down

# Rebuild y reiniciar todo
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Limpiar volúmenes (⚠️ ELIMINA DATOS)
docker-compose down -v
```

### Inference Service

```bash
# Activar entorno conda
conda activate vigias

# Iniciar en foreground (para debug)
cd /home/logisticos-two/dev/Proyect_Computer_Vision
python -m inference.main

# Iniciar en background
nohup python -u -m inference.main > /tmp/inference.log 2>&1 &

# Ver logs en tiempo real
tail -f /tmp/inference.log

# Detener servicio
pkill -f "python.*inference.main"

# Ver proceso
ps aux | grep "python.*inference.main"
```

### Base de Datos

```bash
# Conectar a PostgreSQL
docker exec -it dev_vision-postgres_1 psql -U vision_user -d vigias_vision

# Backup de base de datos
docker exec dev_vision-postgres_1 pg_dump -U vision_user vigias_vision > backup_$(date +%Y%m%d).sql

# Restaurar backup
docker exec -i dev_vision-postgres_1 psql -U vision_user -d vigias_vision < backup_20251226.sql

# Ver tamaño de tablas
docker exec -it dev_vision-postgres_1 psql -U vision_user -d vigias_vision -c "\dt+"
```

### Monitoreo

```bash
# Ver uso de GPU
watch -n 1 nvidia-smi

# Ver uso de CPU/RAM
htop

# Ver espacio en disco
df -h

# Ver logs del sistema
journalctl -f -u docker
```

---

## 🎯 SIGUIENTE PASO

Una vez verificado que todo está funcionando correctamente:

1. ✅ Todos los servicios Docker en estado `healthy`
2. ✅ Inference service cargando modelos exitosamente
3. ✅ Puerto 8003 respondiendo
4. ✅ Cache LFU inicializado
5. ✅ NATS conectado

**Puedes proceder a:**
- Registrar rostros vía API
- Configurar cámaras en la base de datos
- Iniciar captura de streams RTSP
- Ver detecciones en el stream de debug (puerto 5000)

**Para Sprint 1 Day 2:**
- Implementar auto-registro de UNKNOWN en zonas restringidas
- Crear endpoints de Router API para blacklist management

---

## 📞 SOPORTE

**Documentación adicional:**
- [PLAN_DESARROLLO_PRODUCCION.md](AgentFiles/PLAN_DESARROLLO_PRODUCCION.md) - Roadmap completo
- [RESUMEN_EJECUTIVO_PLAN.md](AgentFiles/RESUMEN_EJECUTIVO_PLAN.md) - Resumen ejecutivo
- Router API Docs: http://localhost:8003/docs (Swagger)

**Logs importantes:**
- Inference: `/tmp/inference.log`
- Router API: `docker logs dev-vision-router-1`
- NATS: `docker logs dev-vision-nats-1`
- PostgreSQL: `docker logs dev_vision-postgres_1`

---

**Última actualización**: 2025-12-26
**Versión**: Sprint 1 Day 1 Complete
