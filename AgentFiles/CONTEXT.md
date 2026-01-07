# CONTEXTO DE DESARROLLO - VIGIAS-IA

**Fecha:** 2025-12-16
**Rama actual:** `dev/juancho` (creada desde `development`)
**Desarrollador:** Juancho - Computer Vision Team

---

## 🎯 MISIÓN ACTUAL

Implementar sistema completo de **gestión de zonas** (prohibidas/permitidas) para cámaras, incluyendo:
- CRUD de zonas vía REST API
- Sincronización automática con Redis
- Detección en tiempo real (intrusiones, líneas de cruce)
- Autenticación JWT para proteger endpoints

---

## 📐 ARQUITECTURA DEL SISTEMA

### Stack Tecnológico

| Servicio | Tecnología | Puerto | Propósito |
|----------|-----------|--------|-----------|
| **Ingest** | Go 1.21+ | 8081 | Captura RTSP → NATS (motion detection, JPEG encoding) |
| **Router** | FastAPI Python 3.11+ | 8003 | Enrutamiento inteligente + REST API + WebSocket |
| **Inference** | Python 3.11+ YOLO | - | Procesamiento ML (objetos, rostros, placas, zonas) |
| **NATS** | NATS Server 2.10+ | 4223 | Mensajería pub/sub asíncrona |
| **Redis** | Redis 7.x | 6380 | Caché L2 + configuración de cámaras |
| **PostgreSQL** | pgvector/pg16 | 5436 | Persistencia + búsqueda vectorial |

### Flujo de Datos

```
Cámaras RTSP
    ↓
[INGEST] → NATS: camera.{id}.frame (JPEG + headers)
    ↓
[ROUTER] → Consulta Redis (config) → NATS: work.security, work.lpr
    ↓
[INFERENCE] → Procesa (YOLO, Face, LPR, Zonas) → NATS: events.alarm
    ↓
[DB + WebSocket] → Persiste eventos + Broadcast a clientes
```

### Sujetos NATS Clave

| Sujeto | Productor | Consumidor | Contenido |
|--------|-----------|-----------|-----------|
| `camera.{id}.frame` | Ingest | Router | JPEG bytes + headers (timestamp, config) |
| `work.security` | Router | Inference | JPEG bytes + camera_id |
| `work.lpr` | Router | Inference | JPEG bytes + camera_id |
| `events.alarm` | Inference | Router/DB | JSON evento (camera_id, type, severity) |
| `commands.register_face` | API | Inference | JSON base64 image + name |

### Caché Multinivel (Router)

- **L1 (TTLCache)**: Memoria Python, 100ns, TTL 60s
- **L2 (Redis)**: `config:camera:{id}`, 1-2ms
- **Fallback**: Default services `["security"]`

---

## 🗄️ MODELOS DE BASE DE DATOS

### Tablas Principales

#### `cameras`
```sql
id (SERIAL PK), name, rtsp_url, location_name, meta_info (JSONB),
is_active (BOOL), created_at, updated_at
```

#### `zones` ⭐ **NUEVA TABLA A IMPLEMENTAR**
```sql
id (UUID PK), camera_id (FK), name, zone_type (intrusion|line_crossing),
points (JSONB [[x,y], ...]), trigger (enter|exit|in_out),
classes (JSONB [0,2,5,7]), is_active (BOOL), created_at, updated_at
```

#### `events`
```sql
id (SERIAL PK), camera_id (FK), event_type, track_id, confidence,
snapshot_path, video_clip_path, bbox (JSONB), severity, status,
created_at, occurred_at

-- Índice crítico para debouncing:
INDEX idx_events_debounce (camera_id, event_type, track_id, occurred_at DESC)
```

#### `faces` (pgvector)
```sql
id (SERIAL PK), name, embedding (vector(512)), created_at

-- Búsqueda por similitud:
SELECT id, name, 1 - (embedding <=> :query::vector) as similarity
FROM faces
WHERE 1 - (embedding <=> :query::vector) > :threshold
ORDER BY embedding <=> :query::vector LIMIT 1;
```

#### RBAC: `users`, `roles`, `permissions`, `role_permissions`

---

## 📡 ENDPOINTS ACTUALES

### ✅ Implementados

| Método | Ruta | Propósito |
|--------|------|-----------|
| GET | `/health` | Health check |
| GET | `/system/summary` | Dashboard stats (cameras, events, users, roles) |
| GET/POST/PUT/DELETE | `/users`, `/roles`, `/permissions` | CRUD RBAC completo |
| POST | `/config/{camera_id}` | Actualizar servicios dinámicamente |
| GET | `/api/v1/cameras/` | Listar cámaras |
| POST | `/api/v1/cameras/` | Crear cámara |
| GET | `/api/v1/alarms/` | Listar alarmas (filtros: camera_id, event_type) |
| GET | `/api/v1/alarms/{id}` | Obtener alarma específica |
| GET/POST/DELETE | `/api/v1/faces/` | CRUD reconocimiento facial |
| GET | `/api/v1/stream/{camera_id}/mjpeg` | Stream MJPEG (proxy a ingest) |
| WS | `/ws/notifications` | WebSocket eventos tiempo real |

### ❌ Faltantes (PRIORIDAD ALTA)

| Método | Ruta | Propósito | Prioridad |
|--------|------|-----------|-----------|
| **ZONAS** |
| GET | `/api/v1/cameras/{id}/zones` | Listar zonas de cámara | 🔴 |
| POST | `/api/v1/cameras/{id}/zones` | Crear zona | 🔴 |
| PUT | `/api/v1/cameras/{id}/zones/{zone_id}` | Actualizar zona | 🔴 |
| DELETE | `/api/v1/cameras/{id}/zones/{zone_id}` | Eliminar zona | 🔴 |
| **AUTENTICACIÓN** |
| POST | `/auth/login` | Login JWT | 🔴 |
| GET | `/auth/me` | Usuario actual | 🔴 |
| **CÁMARAS** |
| GET | `/api/v1/cameras/{id}` | Obtener cámara | 🟡 |
| PUT | `/api/v1/cameras/{id}` | Actualizar cámara | 🟡 |
| GET | `/api/v1/cameras/{id}/status` | Estado conexión | 🟡 |
| **ALARMAS** |
| PUT | `/api/v1/alarms/{id}/status` | Actualizar estado (acknowledge, resolve) | 🟡 |
| **ANALÍTICAS** |
| GET | `/api/v1/analytics/events-by-camera` | Eventos agrupados | 🟢 |

---

## 🎨 SISTEMA DE ZONAS (CORE FEATURE)

### Tipos de Zonas

#### 1. Zona de Intrusión (Polígono)

**Propósito:** Detectar entrada/salida de objetos en área prohibida/permitida

**Configuración:**
```json
{
  "zone_type": "intrusion",
  "name": "Bodega Restringida",
  "points": [[100, 200], [500, 200], [500, 600], [100, 600]],
  "trigger": "enter",
  "classes": [0],  // 0=Person
  "is_active": true
}
```

**Triggers:**
- `enter`: Alerta cuando objeto ENTRA (zona prohibida)
- `exit`: Alerta cuando objeto SALE (zona permitida - alertar si salen)
- `in_out`: Ambos eventos

**Clases YOLO:**
- `[0]` = Person
- `[2]` = Car
- `[5]` = Bus
- `[7]` = Truck

#### 2. Línea de Cruce

**Propósito:** Contar objetos que cruzan una línea (entrada/salida)

**Configuración:**
```json
{
  "zone_type": "line_crossing",
  "name": "Entrada Principal",
  "points": [[0, 400], [1280, 400]],
  "trigger": "in_out",
  "classes": [0, 2, 5, 7],
  "is_active": true
}
```

### Flujo de Implementación

```
1. Frontend/API → POST /api/v1/cameras/{id}/zones (crear zona)
    ↓
2. Router → Guardar en DB (tabla zones)
    ↓
3. Router → sync_camera_config_to_redis(camera_id)
    - Lee zonas de DB
    - Construye config JSON
    - Guarda en Redis: config:camera:{id}
    ↓
4. Router → Invalida L1 cache (TTLCache)
    ↓
5. Próximo frame → Router consulta Redis (nueva config con zonas)
    ↓
6. Inference → Recibe frame + config con zonas
    ↓
7. SecurityProcessor → Configura SpatialAnalytics:
    - set_polygon_zone(points, frame_wh)
    - set_line_zone(points, trigger)
    ↓
8. Cada frame → SpatialAnalytics.update(frame, yolo_results)
    - ByteTrack tracking
    - Detecta intrusiones → result.intrusion_events
    - Cuenta cruces → result.line_counts
    ↓
9. Si hay evento → Verificar debouncing (10s por track_id)
    ↓
10. Crear evento en DB + Publicar a NATS events.alarm
    ↓
11. WebSocket → Broadcast a clientes conectados
```

### Debouncing (Evita Duplicados)

**Problema:** Persona en zona genera 15 eventos/seg @ 15 FPS

**Solución:**
```python
def should_create_event(camera_id, event_type, track_id, debounce_seconds=10.0):
    """Retorna True si no hay evento similar en últimos N segundos."""
    threshold = datetime.now() - timedelta(seconds=debounce_seconds)

    existing = db.query(Event).filter(
        Event.camera_id == camera_id,
        Event.event_type == event_type,
        Event.track_id == track_id,
        Event.occurred_at >= threshold
    ).first()

    return existing is None
```

---

## 🚀 PLAN DE IMPLEMENTACIÓN (SPRINT 1)

### Fase 1: Base de Datos (1-2 días)

**Archivos:**
- `router/app/models.py` - Añadir modelo `Zone`
- `router/app/schemas_extended.py` - Añadir `ZoneCreate`, `ZoneUpdate`, `ZoneResponse`
- `database/migrations/` - Crear migración Alembic

**Tareas:**
- [ ] Crear modelo SQLAlchemy `Zone`
- [ ] Crear schemas Pydantic (ZoneBase, ZoneCreate, ZoneUpdate, ZoneResponse)
- [ ] Generar migración: `alembic revision --autogenerate -m "Add zones table"`
- [ ] Aplicar migración: `alembic upgrade head`
- [ ] Verificar tabla creada: `psql -U user -d vigias -c "\d zones"`

### Fase 2: Endpoints CRUD (2-3 días)

**Archivos:**
- `router/app/api/routes/zones.py` - **NUEVO ARCHIVO**
- `router/app/api/routes/__init__.py` - Registrar router

**Endpoints a implementar:**

#### GET `/api/v1/cameras/{camera_id}/zones`
```python
@router.get("/api/v1/cameras/{camera_id}/zones", response_model=List[ZoneResponse])
async def list_zones(camera_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Zone).where(Zone.camera_id == camera_id))
    return result.scalars().all()
```

#### POST `/api/v1/cameras/{camera_id}/zones`
```python
@router.post("/api/v1/cameras/{camera_id}/zones", response_model=ZoneResponse, status_code=201)
async def create_zone(
    camera_id: int,
    zone: ZoneCreate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    # 1. Validar cámara existe
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # 2. Crear zona
    new_zone = Zone(**zone.dict(), camera_id=camera_id)
    db.add(new_zone)
    await db.commit()
    await db.refresh(new_zone)

    # 3. Sincronizar a Redis
    await sync_camera_config_to_redis(camera_id, db, redis)

    # 4. Invalidar L1 cache
    router_cache.invalidate(f"cam_{camera_id}")

    return new_zone
```

#### PUT `/api/v1/cameras/{camera_id}/zones/{zone_id}`
```python
@router.put("/api/v1/cameras/{camera_id}/zones/{zone_id}", response_model=ZoneResponse)
async def update_zone(
    camera_id: int,
    zone_id: UUID,
    zone_update: ZoneUpdate,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    result = await db.execute(
        select(Zone).where(Zone.id == zone_id, Zone.camera_id == camera_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    for field, value in zone_update.dict(exclude_unset=True).items():
        setattr(zone, field, value)

    await db.commit()
    await db.refresh(zone)

    await sync_camera_config_to_redis(camera_id, db, redis)
    router_cache.invalidate(f"cam_{camera_id}")

    return zone
```

#### DELETE `/api/v1/cameras/{camera_id}/zones/{zone_id}`
```python
@router.delete("/api/v1/cameras/{camera_id}/zones/{zone_id}")
async def delete_zone(camera_id: int, zone_id: UUID, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)):
    result = await db.execute(select(Zone).where(Zone.id == zone_id, Zone.camera_id == camera_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    await db.delete(zone)
    await db.commit()

    await sync_camera_config_to_redis(camera_id, db, redis)
    router_cache.invalidate(f"cam_{camera_id}")

    return {"message": "Zone deleted"}
```

### Fase 3: Sincronización DB → Redis (1 día)

**Archivo:**
- `router/app/services/config_sync.py` - **NUEVO ARCHIVO**

**Función clave:**
```python
async def sync_camera_config_to_redis(camera_id: int, db: AsyncSession, redis: Redis):
    """Sincroniza configuración de cámara desde DB a Redis."""

    # Obtener cámara con zonas
    result = await db.execute(
        select(Camera).where(Camera.id == camera_id).options(selectinload(Camera.zones))
    )
    camera = result.scalar_one()

    # Construir config
    config = {
        "services": ["security"],
        "active": camera.is_active,
        "features": [],
        "zones": {},
        "yolo_config": {"confidence": 0.5},
        "intrusion_config": {"debounce": 10.0, "classes": [0]},
        "line_crossing_config": {}
    }

    # Agregar zonas activas
    for zone in camera.zones:
        if not zone.is_active:
            continue

        if zone.zone_type not in config["features"]:
            config["features"].append(zone.zone_type)

        config["zones"][zone.zone_type] = {
            "points": zone.points,
            "trigger": zone.trigger
        }

        if zone.zone_type == "intrusion":
            config["intrusion_config"]["classes"] = zone.classes

    # Guardar en Redis
    await redis.set(f"config:camera:cam_{camera_id}", json.dumps(config))
```

### Fase 4: Testing (1 día)

**Crear archivo:**
- `tests/test_zones.py`

**Tests básicos:**
```python
async def test_create_zone():
    response = client.post("/api/v1/cameras/1/zones", json={
        "name": "Test Zone",
        "zone_type": "intrusion",
        "points": [[100, 200], [500, 200], [500, 600], [100, 600]],
        "trigger": "enter",
        "classes": [0],
        "is_active": true
    })
    assert response.status_code == 201

async def test_list_zones():
    response = client.get("/api/v1/cameras/1/zones")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

async def test_sync_to_redis():
    # Crear zona
    # Verificar que Redis tiene la config actualizada
    config = await redis.get("config:camera:cam_1")
    assert "intrusion" in json.loads(config)["features"]
```

---

## 🔧 COMANDOS ÚTILES

### Docker
```bash
# Ver servicios corriendo
docker ps

# Logs en tiempo real
docker logs -f router
docker logs -f ingest

# Reiniciar servicio
docker restart router

# Shell interactivo
docker exec -it router bash
docker exec -it postgres psql -U user -d vigias
```

### Base de Datos
```bash
# Conectar
docker exec -it postgres psql -U user -d vigias

# Ver tablas
\dt

# Ver zonas
SELECT * FROM zones;

# Ver eventos recientes
SELECT camera_id, event_type, severity, occurred_at
FROM events
ORDER BY occurred_at DESC
LIMIT 20;

# Contar eventos por tipo
SELECT event_type, COUNT(*) as total
FROM events
GROUP BY event_type
ORDER BY total DESC;
```

### Redis
```bash
# Conectar
docker exec -it redis redis-cli

# Ver configs de cámaras
KEYS config:camera:*

# Ver config específica
GET config:camera:cam_1

# Eliminar config (forzar refresh)
DEL config:camera:cam_1
```

### NATS
```bash
# Ver frames de cámaras
docker exec -it nats nats sub "camera.>"

# Ver eventos
docker exec -it nats nats sub "events.>"
```

### API REST (curl)
```bash
# Health check
curl http://localhost:8003/health

# Listar cámaras
curl http://localhost:8003/api/v1/cameras/

# Crear zona
curl -X POST http://localhost:8003/api/v1/cameras/1/zones \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Zona Restringida",
    "zone_type": "intrusion",
    "points": [[100,200],[500,200],[500,600],[100,600]],
    "trigger": "enter",
    "classes": [0],
    "is_active": true
  }'

# Listar zonas
curl http://localhost:8003/api/v1/cameras/1/zones

# Actualizar servicios de cámara
curl -X POST http://localhost:8003/config/cam_1 \
  -H "Content-Type: application/json" \
  -d '["security"]'
```

### Git
```bash
# Ver rama actual
git branch

# Crear/cambiar a rama dev/juancho
git checkout -b dev/juancho

# Ver cambios
git status
git diff

# Commit
git add .
git commit -m "feat: Implement zones CRUD endpoints"

# Push
git push origin dev/juancho
```

---

## 🎯 PRÓXIMOS PASOS INMEDIATOS

### DÍA 1-2: Setup + Base de Datos
1. [ ] Verificar conexión al servidor remoto
2. [ ] Crear rama `dev/juancho` desde `development`
3. [ ] Crear modelo `Zone` en `router/app/models.py`
4. [ ] Crear schemas en `router/app/schemas_extended.py`
5. [ ] Generar y aplicar migración Alembic
6. [ ] Verificar tabla creada en PostgreSQL

### DÍA 3-4: Endpoints CRUD
1. [ ] Crear archivo `router/app/api/routes/zones.py`
2. [ ] Implementar GET `/api/v1/cameras/{id}/zones`
3. [ ] Implementar POST `/api/v1/cameras/{id}/zones`
4. [ ] Implementar PUT `/api/v1/cameras/{id}/zones/{zone_id}`
5. [ ] Implementar DELETE `/api/v1/cameras/{id}/zones/{zone_id}`
6. [ ] Registrar router en `router/app/api/routes/__init__.py`

### DÍA 5: Sincronización Redis
1. [ ] Crear `router/app/services/config_sync.py`
2. [ ] Implementar `sync_camera_config_to_redis()`
3. [ ] Integrar en endpoints (POST, PUT, DELETE zones)
4. [ ] Probar invalidación de L1 cache

### DÍA 6: Testing
1. [ ] Crear `tests/test_zones.py`
2. [ ] Test CRUD completo
3. [ ] Test sincronización Redis
4. [ ] Test invalidación cache
5. [ ] Test detección en inference (manual con cámara de prueba)

### DÍA 7: Documentación + Review
1. [ ] Actualizar Swagger/OpenAPI
2. [ ] Crear Postman collection
3. [ ] Pull Request a `development`
4. [ ] Code review

---

## 📚 REFERENCIAS RÁPIDAS

### Estructura de Archivos Clave

```
router/
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── zones.py         ← CREAR (endpoints CRUD)
│   │       ├── cameras.py
│   │       ├── alarms.py
│   │       └── __init__.py      ← ACTUALIZAR (registrar zones router)
│   ├── services/
│   │   ├── dispatcher.py
│   │   ├── cache.py
│   │   └── config_sync.py       ← CREAR (sync DB → Redis)
│   ├── models.py                ← ACTUALIZAR (añadir Zone)
│   ├── schemas_extended.py      ← ACTUALIZAR (añadir Zone schemas)
│   └── main.py

inference/
├── processors/
│   ├── security.py              ← Ya maneja zonas (SpatialAnalytics)
│   └── spatial.py               ← set_polygon_zone(), set_line_zone()

database/
└── migrations/                  ← Generar migración Alembic
```

### Conexión a Servicios

```python
# PostgreSQL (Async)
from app.core.database import get_db
db: AsyncSession = Depends(get_db)

# Redis
from app.core.redis import get_redis
redis: Redis = Depends(get_redis)

# NATS
from app.core.nats_client import get_nats
nc: NATS = Depends(get_nats)

# Router Cache
from app.services.cache import router_cache
router_cache.invalidate(camera_id)
```

### Clases YOLO (COCO Dataset)

```python
CLASSES = {
    0: "person",
    2: "car",
    5: "bus",
    7: "truck",
    # ... (80 clases totales)
}
```

---

## ⚠️ NOTAS IMPORTANTES

1. **Autenticación JWT**: Actualmente NO implementada. Endpoints están abiertos. Priorizar después de zonas.

2. **Performance GPU**:
   - Sistema actual usa YOLO11n (2.6M params)
   - Batch size: 4 frames
   - Skip factor: 3 (Face/LPR cada 3 frames)
   - VRAM: ~2GB total (YOLO + FaceNet + LPR)

3. **Debouncing**: Crítico para intrusiones. Configurar 10s por defecto (evita alertas spam).

4. **Índices DB**: El índice `idx_events_debounce` es CRÍTICO para performance de debouncing.

5. **Redis TTL**: Config de cámaras NO tiene expiración (manual update via endpoints).

6. **L1 Cache**: TTL 60s. Invalidar SIEMPRE al actualizar config.

---

## 🆘 TROUBLESHOOTING

### Problema: Cambios en zona no se reflejan en detección
**Solución:**
```bash
# 1. Verificar zona en DB
psql -U user -d vigias -c "SELECT * FROM zones WHERE camera_id = 1;"

# 2. Verificar config en Redis
docker exec -it redis redis-cli
GET config:camera:cam_1

# 3. Invalidar L1 cache (hacer request POST para forzar)
curl -X POST http://localhost:8003/config/cam_1 -d '["security"]'
```

### Problema: Eventos duplicados (no funciona debouncing)
**Solución:**
```sql
-- Verificar índice existe
\d events

-- Si no existe, crear:
CREATE INDEX idx_events_debounce
ON events (camera_id, event_type, track_id, occurred_at DESC);
```

### Problema: GPU OOM (Out of Memory)
**Solución:**
```python
# Reducir batch size en inference/main.py
BATCH_SIZE = 2  # En lugar de 4

# O aumentar skip factor
SKIP_FACTOR = 5  # En lugar de 3
```

---

## 📞 CONTACTO Y RECURSOS

- **Documentación completa:** `ANALISIS_DETALLADO_VIGIAS_IA.md`
- **Rama principal:** `main`
- **Rama desarrollo:** `development`
- **Tu rama:** `dev/juancho`

---

**¡Listo para empezar! 🚀**

Usa este documento como referencia rápida. Para detalles técnicos profundos, consulta `ANALISIS_DETALLADO_VIGIAS_IA.md`.
