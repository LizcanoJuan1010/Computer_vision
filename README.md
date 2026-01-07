# VIGIAS-IA: Sistema de Videovigilancia Inteligente

**Versión**: v1.2.0 - Multi-Tenancy Edition
**Fecha**: 2025-12-19

VIGIAS-IA es una plataforma modular de videovigilancia impulsada por Inteligencia Artificial, diseñada para detectar intrusiones, reconocer rostros y gestionar alertas en tiempo real con soporte completo para **multi-tenancy**.

---

## 🎯 Características Principales

✅ **Multi-Tenancy**: Soporte para múltiples organizaciones y zonas geográficas
✅ **Detección Inteligente**: YOLO v11 para objetos, personas, vehículos
✅ **Reconocimiento Facial**: FaceNet con base de datos en memoria
✅ **Lectura de Placas (LPR)**: YOLO v11 optimizado para Colombia
✅ **API RESTful**: FastAPI con validación jerárquica automática
✅ **Tiempo Real**: NATS JetStream para latencia < 100ms
✅ **Alta Performance**: Cache L1/L2, batching, procesamiento asíncrono
✅ **Escalabilidad**: Arquitectura distribuida con microservicios

---

## 🏗️ Arquitectura del Sistema

### Microservicios Dockerizados

```
┌─────────────────────────────────────────────────────────┐
│                    VIGIAS-IA System                     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│  │  Ingest  │──▶│  Router  │──▶│Inference │           │
│  │   (Go)   │   │ (Python) │   │ (Python) │           │
│  └──────────┘   └──────────┘   └──────────┘           │
│       │              │               │                 │
│       ▼              ▼               ▼                 │
│  ┌──────────────────────────────────────────┐          │
│  │         NATS JetStream                   │          │
│  │  • org.{org}.zone.{zone}.camera.{id}     │          │
│  │  • work.security, work.analytics         │          │
│  └──────────────────────────────────────────┘          │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│  │PostgreSQL│   │  Redis   │   │ FastAPI  │           │
│  │  (DB)    │   │ (Cache)  │   │  (API)   │           │
│  └──────────┘   └──────────┘   └──────────┘           │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Componentes

1. **Ingest (Go)**
   - Captura video de cámaras RTSP/archivos
   - Decodifica y redimensiona frames
   - Publica a NATS con contexto multi-tenancy
   - Optimizado para baja latencia (~5ms por frame)

2. **Router (Python/FastAPI)**
   - API REST con 28 endpoints (19 multi-tenancy + 9 legacy)
   - Validación jerárquica automática org→zone→camera
   - Cache L1 (memoria) + L2 (Redis)
   - Dispatcher de frames a servicios (security, analytics)
   - Health checks y admin tools

3. **Inference (Python/YOLO/OpenCV)**
   - Procesamiento por lotes (batching) para performance
   - YOLO v11 para detección de objetos/personas
   - FaceNet para reconocimiento facial
   - YOLO-LPR para lectura de placas
   - Escrituras asíncronas a PostgreSQL

4. **Infrastructure**
   - **NATS**: Bus de mensajería de alto rendimiento
   - **Redis**: Cache de configuración en tiempo real
   - **PostgreSQL**: Base de datos relacional con pgvector

---

## 🌐 Multi-Tenancy

### Jerarquía

```
Organization (Cliente/Empresa)
  └── Zone (Ubicación geográfica: bodega, oficina, zona)
      └── Camera (Cámara individual)
          └── AI Zone Config (ROI, detección personalizada)
```

### URLs de API

**Nuevas (Multi-Tenancy)**:
```http
GET  /api/v1/orgs/
POST /api/v1/orgs/

GET  /api/v1/orgs/{org_slug}/zones/
POST /api/v1/orgs/{org_slug}/zones/

GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/
POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/

GET  /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{id}/zones
POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{id}/zones
```

**Legacy (Deprecated)**:
```http
GET  /api/v1/cameras/  # ⚠️ Sunset: 2026-06-01
POST /api/v1/cameras/  # ⚠️ Deprecated
```

### Ejemplo de Uso

```bash
# 1. Crear organización
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "acme-corp",
    "name": "ACME Corporation",
    "is_managed": true
  }'

# 2. Crear zona
curl -X POST http://localhost:8000/api/v1/orgs/acme-corp/zones/ \
  -d '{
    "slug": "warehouse-1",
    "name": "Warehouse 1",
    "location_description": "Main warehouse downtown"
  }'

# 3. Crear cámara
curl -X POST http://localhost:8000/api/v1/orgs/acme-corp/zones/warehouse-1/cameras/ \
  -d '{
    "name": "Entrance Camera",
    "rtsp_url": "rtsp://192.168.1.100:554/stream",
    "location_name": "Main entrance"
  }'

# 4. Configurar AI Zone (intrusion detection)
curl -X POST http://localhost:8000/api/v1/orgs/acme-corp/zones/warehouse-1/cameras/{id}/zones \
  -d '{
    "event_type": "intrusion",
    "roi_polygon": [[0.1,0.1], [0.9,0.1], [0.9,0.9], [0.1,0.9]],
    "confidence_threshold": 0.7,
    "default_severity": "HIGH"
  }'
```

---

## 🚀 Guía de Inicio Rápido

### Prerrequisitos

- Docker y Docker Compose
- 4GB RAM mínimo (8GB recomendado)
- GPU NVIDIA (opcional, para mejor performance)

### Instalación

```bash
# 1. Clonar repositorio
git clone https://github.com/your-org/vigias-ia.git
cd vigias-ia

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env con credenciales de cámaras RTSP

# 3. Iniciar sistema

docker-compose up -d --build
```

### Verificar Instalación

```bash
# Health check
curl http://localhost:8000/health

# Esperado:
# {
#   "status": "ok",
#   "services": {
#     "database": "ok",
#     "redis": "ok",
#     "nats": "ok"
#   }
# }

# Swagger UI
open http://localhost:8000/docs
```

---

## 📚 Documentación de API

### Base URL

```
Development: http://localhost:8000/api/v1
Production:  https://api.vigias-ia.com/api/v1
```

### Organizations

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/orgs/` | Listar organizaciones |
| POST | `/orgs/` | Crear organización |
| GET | `/orgs/{slug}` | Obtener organización |
| PUT | `/orgs/{slug}` | Actualizar organización |
| DELETE | `/orgs/{slug}` | Soft delete (is_active=false) |

### Zones

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/orgs/{org}/zones/` | Listar zonas |
| POST | `/orgs/{org}/zones/` | Crear zona |
| GET | `/orgs/{org}/zones/{zone}` | Obtener zona |
| PUT | `/orgs/{org}/zones/{zone}` | Actualizar zona |
| DELETE | `/orgs/{org}/zones/{zone}` | Soft delete |

### Cameras

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/orgs/{org}/zones/{zone}/cameras/` | Listar cámaras |
| POST | `/orgs/{org}/zones/{zone}/cameras/` | Crear cámara (zone_id auto-asignado) |
| GET | `/orgs/{org}/zones/{zone}/cameras/{id}` | Obtener cámara |
| PUT | `/orgs/{org}/zones/{zone}/cameras/{id}` | Actualizar cámara |
| DELETE | `/orgs/{org}/zones/{zone}/cameras/{id}` | Soft delete |

### AI Zones (ROI Configs)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/orgs/{org}/zones/{zone}/cameras/{id}/zones` | Listar configs ROI |
| POST | `/orgs/{org}/zones/{zone}/cameras/{id}/zones` | Crear config (intrusion, line_crossing, etc.) |
| PUT | `/orgs/{org}/zones/{zone}/cameras/{id}/zones/{z}` | Actualizar config |
| DELETE | `/orgs/{org}/zones/{zone}/cameras/{id}/zones/{z}` | Eliminar config |

**Event Types Soportados**:
- `intrusion`: Detección de intrusión en zona prohibida
- `loitering`: Detección de merodeo
- `line_crossing`: Cruce de línea virtual
- `abandoned_object`: Objeto abandonado
- `crowd_detection`: Detección de aglomeraciones

### Admin Endpoints

```bash
# Health check avanzado
GET /health

# Cache warmup (poblar Redis desde DB)
POST /admin/cache/warmup
```

### Swagger UI

Documentación interactiva disponible en:
```
http://localhost:8000/docs
```

---

## 🛠️ Herramientas Útiles

### Scripts de Gestión

```bash
# Descubrir cámaras en la red
./list_cameras.sh

# Agregar cámaras al sistema
python tools/add_cameras.py

# Descargar modelo LPR
python tools/download_lpr_model.py
```

### Monitoreo

### Monitoreo (Prometheus)

El sistema incluye una pila de monitoreo ligera basada en Prometheus (sin Grafana) para integración flexible con frontends.

**Endpoints de Acceso:**
*   **Prometheus UI**: [http://localhost:9099](http://localhost:9099)
*   **Inference Metrics**: [http://localhost:8007/metrics](http://localhost:8007/metrics)
*   **Ingest Metrics**: [http://localhost:8088/metrics](http://localhost:8088/metrics)

**Consultas Útiles (PromQL):**

1.  **Verificar estado de servicios (UP/DOWN)**:
    ```promql
    up
    ```
    *Esperado: Value `1` para ambos targets (`ingest`, `inference`).*

2.  **Total de cuadros procesados por la IA**:
    ```promql
    frames_processed_total
    ```

3.  **Cuadros capturados por las cámaras**:
    ```promql
    camera_frames_captured_total
    ```

4.  **Cuadros perdidos (Dropped/Lag)**:
    ```promql
    camera_frames_dropped_total
    ```

### Comandos de depuración

```bash
# Ver logs de todos los servicios
docker-compose logs -f

# Ver logs del router
docker-compose logs -f router

# Ver logs de inference
docker-compose logs -f inference

# Monitorear NATS subjects
docker-compose exec nats nats sub "org.>"

# Ver Redis cache
docker-compose exec redis redis-cli KEYS "config:*"
```

### Testing

```bash
# Test completo del sistema
./test_system.sh

# Ver guía completa de testing
cat AgentFiles/TESTING_GUIDE.md
```

---

## 🛠️ Tecnologías Utilizadas

### Backend
- **Python**: 3.11+ (FastAPI, SQLAlchemy, Pydantic)
- **Go**: 1.21+ (Ingest service)
- **FastAPI**: API REST con validación automática
- **SQLAlchemy 2.0**: ORM con typed mappings
- **Pydantic**: Validación de datos

### IA/Visión
- **YOLO v11**: Detección de objetos (Ultralytics)
- **FaceNet**: Reconocimiento facial (InsightFace)
- **OpenCV**: Procesamiento de imágenes
- **Supervision**: Anotaciones y tracking

### Infraestructura
- **PostgreSQL 16**: Base de datos relacional
- **Redis 7**: Cache en memoria
- **NATS JetStream**: Bus de mensajería
- **Docker**: Contenedores
- **Docker Compose**: Orquestación

---

## 📊 Performance

### Métricas

| Métrica | Valor | Objetivo |
|---------|-------|----------|
| Latencia Router | < 1ms | Sub-microsegundo |
| Throughput Ingest | ~200 FPS | 5 FPS × 40 cámaras |
| L1 Cache Hit Rate | > 95% | Máximo throughput |
| NATS Latency | < 5ms | Tiempo real |
| Inference Batch | 4 frames | Balance latencia/throughput |

### Optimizaciones

✅ **L1/L2 Cache**: Tiered caching con TTL=60s
✅ **Batching**: Procesamiento por lotes en Inference
✅ **Async I/O**: Escrituras asíncronas a PostgreSQL
✅ **Zero-Copy**: Raw bytes en NATS sin deserialización
✅ **Connection Pooling**: PostgreSQL + Redis
✅ **Índices DB**: Composite indexes para queries jerárquicas

---

## 🔒 Seguridad

### Implementado

✅ Validación jerárquica automática (org→zone→camera)
✅ Soft deletes (is_active flag)
✅ Cascade deletes con FK constraints
✅ Slug validation (regex pattern)
✅ Input sanitization (Pydantic)

### Pendiente (Roadmap)

- [ ] JWT Authentication
- [ ] Role-Based Access Control (RBAC)
- [ ] API Rate Limiting
- [ ] Audit Logs
- [ ] Encryption at rest

---

## 📖 Documentación Adicional

### Guías Completas

- **Multi-Tenancy**: `AgentFiles/MULTITENANCY_DOCUMENTATION.md`
- **Testing**: `AgentFiles/TESTING_GUIDE.md`
- **Implementación Fases**: `AgentFiles/implementation_phases_detailed.md`

### Migración

Para migrar de sistema legacy a multi-tenancy, ver:
```
AgentFiles/MULTITENANCY_DOCUMENTATION.md
Sección: "Guía de Migración"
```

---

## 🐛 Troubleshooting

### Problemas Comunes

**Cámara no aparece en zona**:
```sql
SELECT id, name, zone_id FROM cameras WHERE name LIKE '%camera%';
UPDATE cameras SET zone_id = '<zone-uuid>' WHERE id = '<camera-uuid>';
```

**NATS subject no coincide**:
```bash
# Verificar cameras.json tiene org_slug y zone_slug
cat ingest/cameras.json | jq '.[] | {id, org_slug, zone_slug}'
```

**Redis cache miss**:
```bash
curl -X POST http://localhost:8000/admin/cache/warmup
```

Ver guía completa: `AgentFiles/TESTING_GUIDE.md`

---

## 🚀 Roadmap

### v1.3.0 (Q1 2026)
- [ ] Autenticación JWT
- [ ] RBAC completo
- [ ] Dashboard web (React)

### v2.0.0 (2026-06-01)
- [ ] Remover endpoints legacy
- [ ] GraphQL API
- [ ] WebSockets para eventos en tiempo real
- [ ] Multi-región support

---

## 🤝 Contribuir

```bash
# 1. Fork el repositorio
# 2. Crear feature branch
git checkout -b feature/nueva-funcionalidad

# 3. Commit cambios
git commit -m "feat: agregar nueva funcionalidad"

# 4. Push y crear PR
git push origin feature/nueva-funcionalidad
```

---

## 📝 Licencia

Copyright © 2025 VIGIAS-IA Team

---

## 📞 Soporte

- **Issues**: https://github.com/your-org/vigias-ia/issues
- **Docs**: http://docs.vigias-ia.com
- **Email**: support@vigias-ia.com

---

**Built with ❤️ using Claude Code**

🤖 *Multi-tenancy implementation generated with [Claude Code](https://claude.com/claude-code)*
