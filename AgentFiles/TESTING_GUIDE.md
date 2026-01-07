# Guía de Testing - Multi-Tenancy VIGIAS-IA

**Versión**: 1.0.0
**Fecha**: 2025-12-19

---

## 🧪 Testing Checklist

### Database & Models

- [ ] **Tabla organizations**: Creada con constraints correctos
- [ ] **Tabla org_zones**: FK a organizations con CASCADE
- [ ] **Tabla cameras**: Campo zone_id agregado
- [ ] **Índices**: Verificar performance de queries jerárquicas
- [ ] **Soft deletes**: is_active funciona correctamente
- [ ] **Cascades**: DELETE org elimina zones y cameras
- [ ] **Slugs únicos**: No duplicados en organizations.slug
- [ ] **Slugs por org**: org_zones permite duplicados entre orgs diferentes

### API Endpoints - Organizations

```bash
# ✓ Crear organización
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -H "Content-Type: application/json" \
  -d '{"slug": "test-org", "name": "Test Organization"}'
# Esperar: 201 Created

# ✓ Listar organizaciones
curl http://localhost:8000/api/v1/orgs/ | jq
# Esperar: Array con organizaciones

# ✓ Obtener organización
curl http://localhost:8000/api/v1/orgs/test-org | jq
# Esperar: Objeto organización

# ✗ Crear org con slug duplicado
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "test-org", "name": "Duplicate"}'
# Esperar: 409 Conflict

# ✗ Slug con mayúsculas
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "TEST-ORG", "name": "Invalid"}'
# Esperar: 400 Bad Request

# ✗ Slug con underscores
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "test_org", "name": "Invalid"}'
# Esperar: 400 Bad Request

# ✓ Actualizar organización
curl -X PUT http://localhost:8000/api/v1/orgs/test-org \
  -d '{"name": "Test Organization Updated"}'
# Esperar: 200 OK

# ✓ Soft delete
curl -X DELETE http://localhost:8000/api/v1/orgs/test-org
# Esperar: 204 No Content

# Verificar is_active=false en DB
psql -U user vigias -c "SELECT slug, is_active FROM organizations WHERE slug='test-org';"
```

### API Endpoints - Zones

```bash
# Setup: Crear org primero
ORG="test-org"
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "'$ORG'", "name": "Test Org"}'

# ✓ Crear zona
curl -X POST http://localhost:8000/api/v1/orgs/$ORG/zones/ \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "warehouse-1",
    "name": "Warehouse 1",
    "location_description": "Main warehouse"
  }'
# Esperar: 201 Created

# ✓ Listar zonas
curl http://localhost:8000/api/v1/orgs/$ORG/zones/ | jq
# Esperar: Array con zonas

# ✗ Crear zona en org inexistente
curl -X POST http://localhost:8000/api/v1/orgs/invalid-org/zones/ \
  -d '{"slug": "zone-1", "name": "Zone"}'
# Esperar: 404 Not Found

# ✓ Dos zonas con mismo slug en orgs diferentes
curl -X POST http://localhost:8000/api/v1/orgs/test-org/zones/ \
  -d '{"slug": "common-zone", "name": "Common"}'

curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "other-org", "name": "Other"}'

curl -X POST http://localhost:8000/api/v1/orgs/other-org/zones/ \
  -d '{"slug": "common-zone", "name": "Common"}'
# Esperar: Ambas 201 Created (slug único por org)

# ✗ Zona duplicada en misma org
curl -X POST http://localhost:8000/api/v1/orgs/$ORG/zones/ \
  -d '{"slug": "warehouse-1", "name": "Duplicate"}'
# Esperar: 409 Conflict
```

### API Endpoints - Cameras

```bash
# Setup
ORG="test-org"
ZONE="warehouse-1"

# ✓ Crear cámara
CAMERA=$(curl -s -X POST \
  http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Camera",
    "rtsp_url": "rtsp://test.local/stream",
    "location_name": "Test Location"
  }')

CAMERA_ID=$(echo $CAMERA | jq -r '.id')
echo "Camera ID: $CAMERA_ID"

# ✓ Verificar zone_id auto-asignado
echo $CAMERA | jq '{id, name, zone_id}'
# Esperar: zone_id no nulo

# ✓ Listar cámaras en zona
curl http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/ | jq

# ✗ Acceder cámara desde zona incorrecta
curl http://localhost:8000/api/v1/orgs/$ORG/zones/wrong-zone/cameras/$CAMERA_ID
# Esperar: 404 Not Found

# ✗ Acceder cámara desde org incorrecta
curl http://localhost:8000/api/v1/orgs/wrong-org/zones/$ZONE/cameras/$CAMERA_ID
# Esperar: 404 Not Found

# ✓ Actualizar cámara
curl -X PUT \
  http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID \
  -d '{"name": "Updated Camera"}'
# Esperar: 200 OK
```

### API Endpoints - AI Zones

```bash
# ✓ Crear AI Zone (intrusion)
AI_ZONE=$(curl -s -X POST \
  http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/zones \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "intrusion",
    "roi_polygon": [[0.1,0.1], [0.9,0.1], [0.9,0.9], [0.1,0.9]],
    "confidence_threshold": 0.7,
    "debounce_seconds": 5.0,
    "default_severity": "HIGH"
  }')

AI_ZONE_ID=$(echo $AI_ZONE | jq -r '.id')

# ✓ Listar AI zones
curl http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/zones | jq

# ✗ Duplicar event_type en misma cámara
curl -X POST \
  http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/zones \
  -d '{
    "event_type": "intrusion",
    "roi_polygon": [[0.2,0.2], [0.8,0.8]],
    "confidence_threshold": 0.6
  }'
# Esperar: 409 Conflict (constraint unique event_type por camera)

# ✓ Crear otro event_type
curl -X POST \
  http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/zones \
  -d '{
    "event_type": "line_crossing",
    "roi_polygon": [[0.3,0.5], [0.7,0.5]],
    "confidence_threshold": 0.8
  }'
# Esperar: 201 Created

# ✗ ROI polygon inválido (< 3 puntos)
curl -X POST \
  http://localhost:8000/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/zones \
  -d '{
    "event_type": "loitering",
    "roi_polygon": [[0.1,0.1], [0.9,0.9]],
    "confidence_threshold": 0.5
  }'
# Esperar: 400 Bad Request
```

### Service Layer - Router

```bash
# ✓ Verificar doble suscripción NATS
docker-compose logs router | grep "Subscribed"
# Esperar:
# Subscribed to LEGACY subject: camera.*.frame
# Subscribed to MULTI-TENANT subject: org.*.zone.*.camera.*.frame

# ✓ Health check
curl http://localhost:8000/health | jq
# Esperar: status "ok", todos los servicios "ok"

# ✓ Cache warmup
WARMUP=$(curl -s -X POST http://localhost:8000/admin/cache/warmup)
echo $WARMUP | jq
# Esperar: cameras_warmed > 0, errors []

# ✓ Verificar Redis keys multi-tenant
docker-compose exec redis redis-cli KEYS "config:org:*"
# Esperar: Keys con formato config:org:{org}:zone:{zone}:camera:{id}

# ✓ Verificar Redis key legacy (backward compat)
docker-compose exec redis redis-cli KEYS "config:camera:*"
# Esperar: Keys legacy si hay cámaras sin org/zone
```

### Service Layer - Ingest

```bash
# ✓ Verificar cameras.json tiene org_slug y zone_slug
cat ingest/cameras.json | jq '.[] | {id, org_slug, zone_slug}'
# Esperar: Todos con org_slug y zone_slug no nulos

# ✓ Rebuild Ingest
cd ingest
go build -o bin/ingest cmd/server/main.go
# Esperar: Sin errores de compilación

# ✓ Monitor NATS subjects publicados
docker-compose exec nats nats sub "org.>"
# Esperar: Subjects con formato org.{org}.zone.{zone}.camera.{id}.frame

# ✓ Verificar headers NATS
docker-compose exec nats nats sub "org.>" --header
# Esperar: Headers: camera_id, org_slug, zone_slug, Timestamp
```

### Service Layer - Inference

```bash
# ✓ Verificar parsing de subjects multi-tenant
docker-compose logs inference | grep "org_slug"
# Esperar: Logs mostrando org_slug y zone_slug extraídos

# ✓ Verificar Redis lookup multi-tenant
docker-compose logs inference | grep "config:org:"
# Esperar: Logs mostrando Redis keys con formato multi-tenant

# ✓ Test con subject legacy (backward compat)
# Publicar manualmente con nats-cli
docker-compose exec nats nats pub camera.test_cam.frame "test payload"
# Verificar inference procesa sin errores
```

### Deprecation Warnings

```bash
# ✓ Verificar headers de deprecación
curl -I http://localhost:8000/api/v1/cameras/
# Esperar headers:
# X-Deprecated: true
# X-Sunset: 2026-06-01
# Link: </api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/>; rel="alternate"

# ✓ Verificar Swagger muestra tag "Cameras (Legacy)"
curl http://localhost:8000/openapi.json | jq '.paths["/api/v1/cameras/"].get.tags'
# Esperar: ["Cameras (Legacy)"]
```

---

## 🔄 Test de Migración

### Migración de cámaras legacy a multi-tenancy

```sql
-- 1. Estado inicial: Cámaras sin zone_id
SELECT id, name, zone_id FROM cameras WHERE zone_id IS NULL;

-- 2. Crear org y zona de migración
INSERT INTO organizations (slug, name) VALUES ('migrated', 'Migrated Cameras');
INSERT INTO org_zones (organization_id, slug, name)
SELECT id, 'legacy-zone', 'Legacy Zone' FROM organizations WHERE slug = 'migrated';

-- 3. Migrar cámaras
UPDATE cameras
SET zone_id = (SELECT id FROM org_zones WHERE slug = 'legacy-zone')
WHERE zone_id IS NULL;

-- 4. Verificar migración exitosa
SELECT COUNT(*) FROM cameras WHERE zone_id IS NULL;
-- Esperar: 0

-- 5. Verificar jerarquía
SELECT
    o.slug as org,
    z.slug as zone,
    COUNT(c.id) as cameras
FROM organizations o
JOIN org_zones z ON z.organization_id = o.id
LEFT JOIN cameras c ON c.zone_id = z.id
GROUP BY o.slug, z.slug;
```

---

## ⚡ Test de Performance

### Latency del Dispatcher

```bash
# Medir latencia de routing
# En logs del router, buscar:
docker-compose logs router | grep "process_frame"

# Objetivo: < 1ms por frame
```

### L1 Cache Hit Rate

```python
# Agregar en router/app/services/cache.py
import time

hit_count = 0
miss_count = 0

async def get_services(...):
    global hit_count, miss_count
    if cache_key in self.l1:
        hit_count += 1
        return self.l1[cache_key]
    else:
        miss_count += 1

    # Log cada 100 requests
    if (hit_count + miss_count) % 100 == 0:
        hit_rate = hit_count / (hit_count + miss_count) * 100
        logger.info(f"L1 cache hit rate: {hit_rate:.2f}%")
```

**Objetivo**: > 95% hit rate

### Database Query Performance

```sql
-- Activar pg_stat_statements
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Ver queries más lentas
SELECT
    query,
    calls,
    mean_exec_time,
    max_exec_time
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Objetivo: mean_exec_time < 10ms para queries frecuentes
```

---

## 🚨 Test de Casos Edge

### Cascada de deletes

```bash
# 1. Crear jerarquía completa
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "cascade-test", "name": "Cascade Test"}'

curl -X POST http://localhost:8000/api/v1/orgs/cascade-test/zones/ \
  -d '{"slug": "zone-1", "name": "Zone 1"}'

CAMERA=$(curl -s -X POST \
  http://localhost:8000/api/v1/orgs/cascade-test/zones/zone-1/cameras/ \
  -d '{"name": "Camera 1", "rtsp_url": "rtsp://test"}')
CAMERA_ID=$(echo $CAMERA | jq -r '.id')

curl -X POST \
  http://localhost:8000/api/v1/orgs/cascade-test/zones/zone-1/cameras/$CAMERA_ID/zones \
  -d '{"event_type": "intrusion", "roi_polygon": [[0,0],[1,0],[1,1]], "confidence_threshold": 0.5}'

# 2. Verificar todo existe
psql -U user vigias -c "
SELECT
    (SELECT COUNT(*) FROM organizations WHERE slug='cascade-test') as orgs,
    (SELECT COUNT(*) FROM org_zones WHERE slug='zone-1') as zones,
    (SELECT COUNT(*) FROM cameras WHERE id='$CAMERA_ID') as cameras,
    (SELECT COUNT(*) FROM camera_ai_configs WHERE camera_id='$CAMERA_ID') as ai_configs;
"
# Esperar: 1, 1, 1, 1

# 3. Eliminar organización
curl -X DELETE http://localhost:8000/api/v1/orgs/cascade-test

# 4. Verificar cascade delete (is_active=false)
psql -U user vigias -c "
SELECT
    (SELECT is_active FROM organizations WHERE slug='cascade-test') as org_active,
    (SELECT COUNT(*) FROM org_zones WHERE slug='zone-1' AND is_active=true) as zones_active,
    (SELECT COUNT(*) FROM cameras WHERE id='$CAMERA_ID' AND is_active=true) as cameras_active;
"
# Esperar: false, 0, 0
```

### Concurrencia

```bash
# Test de creación concurrente (evitar race conditions)
for i in {1..10}; do
  curl -X POST http://localhost:8000/api/v1/orgs/ \
    -d '{"slug": "concurrent-'$i'", "name": "Concurrent '$i'"}' &
done
wait

# Verificar todas creadas
curl http://localhost:8000/api/v1/orgs/ | jq '[.[] | select(.slug | startswith("concurrent"))] | length'
# Esperar: 10
```

### Unicode y caracteres especiales

```bash
# ✗ Slug con tildes
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "compañía", "name": "Test"}'
# Esperar: 400 Bad Request

# ✓ Name con tildes (permitido)
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "compania", "name": "Compañía de Prueba"}'
# Esperar: 201 Created

# ✗ Slug con espacios
curl -X POST http://localhost:8000/api/v1/orgs/ \
  -d '{"slug": "my org", "name": "Test"}'
# Esperar: 400 Bad Request
```

---

## ✅ Checklist Final

### Pre-Deployment

- [ ] Todas las migraciones SQL aplicadas
- [ ] Backup de DB creado
- [ ] Variables de entorno configuradas
- [ ] Docker images rebuildeadas
- [ ] Redis cache warmed
- [ ] Health check retorna "ok"

### Post-Deployment

- [ ] NATS subjects monitoreados (legacy + multi-tenant)
- [ ] Redis keys verificadas (ambos formatos)
- [ ] Logs sin errores
- [ ] Swagger UI accesible
- [ ] Legacy endpoints retornan deprecation headers
- [ ] Performance dentro de objetivos (< 1ms routing)

### Rollback Plan

```bash
# Si algo falla, rollback:
git checkout <commit-anterior>
docker-compose build router
docker-compose up -d router

# Restore DB desde backup
docker-compose exec postgres psql -U user vigias < backup_before_multitenancy.sql
```

---

**Creado**: 2025-12-19
**Autor**: Claude Sonnet 4.5
