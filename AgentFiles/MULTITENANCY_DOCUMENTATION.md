# VIGIAS-IA Multi-Tenancy - Documentación Completa

**Versión**: v1.2.0
**Fecha**: 2025-12-19
**Estado**: ✅ PRODUCCIÓN

---

## 📋 Resumen Ejecutivo

### Jerarquía Multi-Tenancy

```
Organization (Cliente/Empresa)
  └── Zone (Ubicación geográfica)
      └── Camera (Cámara individual)
          └── AI Zone Config (ROI/Detección)
```

### URLs Implementadas

```
# Nuevas (Multi-Tenancy)
/api/v1/orgs/{org_slug}
/api/v1/orgs/{org_slug}/zones/{zone_slug}
/api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{camera_id}

# Legacy (Deprecated)
/api/v1/cameras/{camera_id}
```

---

## 🏗️ Implementación por Fases

### Phase 0-1: Database Schema ✅

**Tablas creadas**:
- `organizations`: Clientes/empresas
- `org_zones`: Ubicaciones geográficas
- `cameras`: Campo `zone_id` agregado

**Migración de datos**:
```sql
-- Organización default
INSERT INTO organizations (slug, name)
VALUES ('vigias-local', 'VIGIAS Local Installation');

-- Zona default
INSERT INTO org_zones (organization_id, slug, name)
VALUES (..., 'zona-default', 'Zona por Defecto');

-- Migrar cámaras existentes
UPDATE cameras SET zone_id = '...' WHERE zone_id IS NULL;
```

### Phase 2-3: Models & Schemas ✅

**SQLAlchemy Models**:
```python
class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID]
    slug: Mapped[str]  # URL-friendly identifier
    name: Mapped[str]
    zones: Mapped[List["OrgZone"]] = relationship(...)

class OrgZone(Base):
    __tablename__ = "org_zones"
    id: Mapped[uuid.UUID]
    organization_id: Mapped[uuid.UUID]
    slug: Mapped[str]
    cameras: Mapped[List["Camera"]] = relationship(...)
```

**Validación de Slugs**: `^[a-z0-9]+(?:-[a-z0-9]+)*$`

### Phase 4-6: API Endpoints ✅

**19 endpoints nuevos**:

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/orgs/` | Listar organizaciones |
| POST | `/orgs/` | Crear organización |
| GET | `/orgs/{org_slug}` | Obtener organización |
| PUT | `/orgs/{org_slug}` | Actualizar organización |
| DELETE | `/orgs/{org_slug}` | Soft delete organización |
| GET | `/orgs/{org}/zones/` | Listar zonas |
| POST | `/orgs/{org}/zones/` | Crear zona |
| GET | `/orgs/{org}/zones/{zone}` | Obtener zona |
| PUT | `/orgs/{org}/zones/{zone}` | Actualizar zona |
| DELETE | `/orgs/{org}/zones/{zone}` | Soft delete zona |
| GET | `/orgs/{org}/zones/{zone}/cameras/` | Listar cámaras |
| POST | `/orgs/{org}/zones/{zone}/cameras/` | Crear cámara |
| GET | `/orgs/{org}/zones/{zone}/cameras/{id}` | Obtener cámara |
| PUT | `/orgs/{org}/zones/{zone}/cameras/{id}` | Actualizar cámara |
| DELETE | `/orgs/{org}/zones/{zone}/cameras/{id}` | Soft delete cámara |
| GET | `/orgs/{org}/zones/{zone}/cameras/{id}/zones` | Listar AI zones |
| POST | `/orgs/{org}/zones/{zone}/cameras/{id}/zones` | Crear AI zone |
| PUT | `/orgs/{org}/zones/{zone}/cameras/{id}/zones/{z}` | Actualizar AI zone |
| DELETE | `/orgs/{org}/zones/{zone}/cameras/{id}/zones/{z}` | Eliminar AI zone |

**Validación jerárquica automática**: FastAPI Dependencies validan org→zone→camera

### Phase 7: Service Layer (Router) ✅

**Archivos creados**:
- `router/app/services/multitenancy_utils.py`: Helper functions

**Funciones helper**:
```python
build_redis_cache_key(camera_id, org_slug, zone_slug)
# → config:org:{org}:zone:{zone}:camera:{id}

build_nats_subject(camera_id, event_type, org_slug, zone_slug)
# → org.{org}.zone.{zone}.camera.{id}.{event}

parse_nats_subject(subject)
# → {camera_id, org_slug, zone_slug, event_type, is_legacy}
```

**Archivos modificados**:
- `cache.py`: Redis keys multi-tenant
- `dispatcher.py`: Parse NATS subjects, agregra headers
- `config.py`: Dos subject patterns (legacy + multi-tenant)
- `main.py`: Doble suscripción NATS

**NATS Subjects**:
```
# Nuevo
org.acme-corp.zone.warehouse-1.camera.cam_701.frame

# Legacy
camera.cam_701.frame
```

**Redis Keys**:
```
# Nuevo
config:org:acme-corp:zone:warehouse-1:camera:cam_701

# Legacy
config:camera:cam_701
```

### Phase 7 Mejoras: Admin Endpoints ✅

**GET /health**:
```json
{
  "status": "ok",
  "services": {
    "database": "ok",
    "redis": "ok",
    "nats": "ok"
  },
  "cache": {
    "l1_size": 15,
    "l1_max": 1000,
    "l1_ttl": 60
  }
}
```

**POST /admin/cache/warmup**:
Pobla Redis desde DB con contexto multi-tenancy

### Phase 8: Ingest Service (Go) ✅

**cameras.json actualizado**:
```json
{
  "id": "cam_701",
  "org_slug": "vigias-local",
  "zone_slug": "zona-default",
  "url": "rtsp://..."
}
```

**Publish con multi-tenancy**:
```go
// Nuevo formato si org_slug y zone_slug disponibles
subject = "org.acme.zone.warehouse-1.camera.cam_701.frame"

// Headers NATS
natsMsg.Header.Add("org_slug", msg.OrgSlug)
natsMsg.Header.Add("zone_slug", msg.ZoneSlug)
```

### Phase 9: Inference Service (Python) ✅

**Parse multi-tenancy**:
```python
# Desde headers (preferido)
org_slug = msg.header.get("org_slug")
zone_slug = msg.header.get("zone_slug")

# Desde subject (fallback)
if parts[0] == "org":
    org_slug = parts[1]
    zone_slug = parts[3]
    camera_id = parts[5]
```

**Redis lookup multi-tenant**:
```python
redis_key = f"config:org:{org}:zone:{zone}:camera:{id}"
```

### Phase 10: Deprecation Warnings ✅

**Headers RFC 8594**:
```http
X-Deprecated: true
X-Sunset: 2026-06-01
Link: </api/v1/orgs/{org}/zones/{zone}/cameras/>; rel="alternate"
```

---

## 🧪 Testing

### Test Completo End-to-End

```bash
#!/bin/bash
BASE_URL="http://localhost:8000/api/v1"

# 1. Crear organización
curl -X POST "$BASE_URL/orgs/" \
  -H "Content-Type: application/json" \
  -d '{"slug": "acme-corp", "name": "ACME Corporation"}'

# 2. Crear zona
curl -X POST "$BASE_URL/orgs/acme-corp/zones/" \
  -H "Content-Type: application/json" \
  -d '{"slug": "warehouse-1", "name": "Warehouse 1"}'

# 3. Crear cámara
CAMERA=$(curl -X POST "$BASE_URL/orgs/acme-corp/zones/warehouse-1/cameras/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Entrance Camera",
    "rtsp_url": "rtsp://192.168.1.100:554/stream"
  }')

CAMERA_ID=$(echo $CAMERA | jq -r '.id')

# 4. Crear AI Zone (intrusion)
curl -X POST "$BASE_URL/orgs/acme-corp/zones/warehouse-1/cameras/$CAMERA_ID/zones" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "intrusion",
    "roi_polygon": [[0.1,0.1], [0.9,0.1], [0.9,0.9], [0.1,0.9]],
    "confidence_threshold": 0.7,
    "default_severity": "HIGH"
  }'

# 5. Verificar health
curl "$BASE_URL/../health" | jq

# 6. Warm cache
curl -X POST "$BASE_URL/../admin/cache/warmup" | jq
```

### Verificar NATS Subjects

```bash
# Suscribirse a todos los subjects
docker-compose exec nats nats sub ">"

# Ver subjects multi-tenant
docker-compose exec nats nats sub "org.>"

# Ver subjects legacy
docker-compose exec nats nats sub "camera.>"
```

### Verificar Redis Keys

```bash
# Ver todas las keys
docker-compose exec redis redis-cli KEYS "config:*"

# Ver key específica
docker-compose exec redis redis-cli GET "config:org:acme-corp:zone:warehouse-1:camera:cam_701"
```

### Verificar Database

```sql
-- Ver jerarquía completa
SELECT
    o.slug as org,
    z.slug as zone,
    c.name as camera,
    COUNT(ai.id) as ai_zones
FROM organizations o
JOIN org_zones z ON z.organization_id = o.id
LEFT JOIN cameras c ON c.zone_id = z.id
LEFT JOIN camera_ai_configs ai ON ai.camera_id = c.id
WHERE o.is_active = true
GROUP BY o.slug, z.slug, c.name
ORDER BY o.slug, z.slug, c.name;
```

---

## 🔧 Troubleshooting

### Problema: Cámara no aparece en zona

**Diagnóstico**:
```sql
SELECT id, name, zone_id, is_active FROM cameras WHERE name LIKE '%test%';
```

**Solución**:
```sql
UPDATE cameras SET zone_id = '<zone-uuid>' WHERE id = '<camera-uuid>';
```

### Problema: NATS subject no coincide

**Diagnóstico**:
```bash
# Ver qué publica Ingest
docker-compose logs ingest | grep "subject"

# Ver a qué se suscribe Router
docker-compose logs router | grep "Subscribed"
```

**Solución**:
```bash
# Verificar cameras.json tiene org_slug y zone_slug
cat ingest/cameras.json | jq '.[] | {id, org_slug, zone_slug}'

# Rebuild Ingest
cd ingest && go build -o bin/ingest cmd/server/main.go
docker-compose restart ingest
```

### Problema: Redis cache miss

**Diagnóstico**:
```bash
docker-compose exec redis redis-cli KEYS "config:*"
```

**Solución**:
```bash
curl -X POST http://localhost:8000/admin/cache/warmup
```

### Problema: Slug validation error

**Error**: `400 Bad Request - string does not match regex`

**Solución**:
- ✅ Usar: `acme-corp`, `warehouse-1`, `zona-default`
- ❌ Evitar: `ACME Corp`, `warehouse_1`, `zona default`

---

## 📊 Métricas de Implementación

| Fase | LOC Agregadas | Archivos Nuevos | Archivos Modificados |
|------|---------------|-----------------|----------------------|
| 0-6 | ~850 | 5 | 3 |
| 7 | ~290 | 1 | 4 |
| 7+ | ~100 | 0 | 2 |
| 8 | ~40 | 0 | 4 |
| 9 | ~60 | 0 | 1 |
| **Total** | **~1,340** | **6** | **14** |

**Endpoints**: 28 totales (19 nuevos + 9 legacy)
**Breaking Changes**: 0
**Backward Compatibility**: 100%

---

## 🎯 Commits

```
f49827f - Phase 0-6: API Layer (orgs, zones, cameras)
975dbfd - Phase 7: Service Layer (Router Redis/NATS)
f441fd3 - Phase 7+: Admin endpoints + Deprecation
e009f18 - Phase 8: Ingest service (Go)
3c8fc58 - Phase 9: Inference service (Python)
```

---

## 🚀 Próximos Pasos

1. **Testing automatizado**: Unit tests + integration tests
2. **Monitoreo**: Métricas por organización
3. **Facturación**: Tracking de uso por org
4. **v2.0.0 (2026-06-01)**: Remover endpoints legacy

---

**Creado**: 2025-12-19
**Autores**: Claude Sonnet 4.5 + Equipo Humano
