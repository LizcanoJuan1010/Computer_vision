# GUÍA RÁPIDA DE TESTING - VIGIAS-IA v1.3.0

## 🚀 INICIO RÁPIDO (5 minutos)

Esta guía te ayudará a levantar el sistema completo y probar los nuevos endpoints implementados.

---

## 📋 PRE-REQUISITOS

✅ Docker y Docker Compose instalados
✅ Puerto 8003 disponible (Router API)
✅ Puerto 5436 disponible (PostgreSQL)
✅ Puerto 4223 disponible (NATS)
✅ Puerto 6380 disponible (Redis)
✅ Migración SQL ejecutada (✓ COMPLETADO)

---

## 🔧 PASO 1: LEVANTAR EL SISTEMA

### 1.1 Desde el directorio del proyecto:

```bash
cd /home/logisticos-two/dev/Proyect_Computer_Vision
```

### 1.2 Levantar servicios:

```bash
# Opción A: Levantar todo (incluye inference e ingest)
docker-compose up -d

# Opción B: Solo servicios base (recomendado para testing de endpoints)
docker-compose up -d postgres redis nats router

# Esperar a que los servicios estén listos (15-20 segundos)
sleep 20
```

### 1.3 Verificar que todo esté corriendo:

```bash
docker-compose ps
```

**Salida esperada**:
```
                    Name                                   Command               State                         Ports
-------------------------------------------------------------------------------------------------------------------------------
proyect_computer_vision_nats_1       /nats-server -js                 Up      0.0.0.0:4223->4222/tcp, 0.0.0.0:8223->8222/tcp
proyect_computer_vision_postgres_1   docker-entrypoint.sh postgres    Up      0.0.0.0:5436->5432/tcp
proyect_computer_vision_redis_1      docker-entrypoint.sh redis ...   Up      0.0.0.0:6380->6379/tcp
proyect_computer_vision_router_1     uvicorn app.main:app --hos ...   Up      0.0.0.0:8003->8000/tcp
```

### 1.4 Verificar logs del router:

```bash
docker-compose logs -f router --tail=50
```

**Buscar estas líneas** (indica que todo está OK):
```
router-1  | INFO:     Uvicorn running on http://0.0.0.0:8000
router-1  | INFO:     Connected to NATS at nats://nats:4222
router-1  | INFO:     Subscribed to LEGACY subject: camera.*.frame
router-1  | INFO:     Subscribed to MULTI-TENANT subject: org.*.zone.*.camera.*.frame
```

**Presiona Ctrl+C** para salir de los logs.

---

## 🌐 PASO 2: ACCEDER A LA DOCUMENTACIÓN INTERACTIVA

### 2.1 Swagger UI (Recomendado):

Abre en tu navegador:
```
http://localhost:8003/docs
```

Deberías ver **todas las secciones nuevas**:
- ✅ Events
- ✅ Faces (Multi-tenancy)
- ✅ Camera Management
- ✅ Notifications & Alerts
- ✅ Organizations, Zones, Cameras

### 2.2 ReDoc (Documentación alternativa):

```
http://localhost:8003/redoc
```

---

## 🧪 PASO 3: TESTING BÁSICO DE ENDPOINTS

### 3.1 Health Check (Verificar que el sistema responde):

```bash
curl http://localhost:8003/health | jq
```

**Salida esperada**:
```json
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "nats": "connected"
}
```

### 3.2 Listar Organizaciones:

```bash
curl http://localhost:8003/api/v1/orgs/ | jq
```

**Salida esperada**:
```json
[
  {
    "id": "uuid-aqui",
    "slug": "default",
    "name": "Default Organization",
    "is_managed": false,
    "config": {},
    "is_active": true,
    "created_at": "2025-12-23T..."
  }
]
```

**Si NO hay organizaciones**, crea una:
```bash
curl -X POST http://localhost:8003/api/v1/orgs/ \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "acme-corp",
    "name": "ACME Corporation",
    "is_managed": false,
    "config": {},
    "is_active": true
  }' | jq
```

---

## 📊 PASO 4: PROBAR NUEVOS ENDPOINTS (Módulo por Módulo)

### 4.1 EVENTOS/ALARMAS

#### Listar eventos de una organización:
```bash
# Reemplaza 'acme-corp' con el slug de tu organización
curl "http://localhost:8003/api/v1/orgs/acme-corp/events/?limit=10" | jq
```

#### Filtrar eventos por severidad:
```bash
curl "http://localhost:8003/api/v1/orgs/acme-corp/events/?severity=CRITICAL&status=PENDING" | jq
```

---

### 4.2 RECONOCIMIENTO FACIAL

#### Listar rostros de una organización:
```bash
curl "http://localhost:8003/api/v1/orgs/acme-corp/faces/" | jq
```

#### Registrar un rostro (requiere imagen):
```bash
# Ejemplo con imagen de prueba
curl -X POST "http://localhost:8003/api/v1/orgs/acme-corp/faces/" \
  -F "file=@/ruta/a/foto.jpg" \
  -F "name=Juan Pérez" \
  -F "category=KNOWN" \
  -F 'meta_info={"employee_id": "EMP001", "department": "Seguridad"}'
```

**Nota**: Necesitas tener una imagen de prueba. Puedes usar cualquier foto JPEG.

#### Listar rostros por categoría:
```bash
# Solo BLACKLIST
curl "http://localhost:8003/api/v1/orgs/acme-corp/faces/?category=BLACKLIST" | jq

# Solo KNOWN
curl "http://localhost:8003/api/v1/orgs/acme-corp/faces/?category=KNOWN" | jq
```

---

### 4.3 GESTIÓN DE CÁMARAS (Endpoints Cliente)

#### Ver status de una cámara:
```bash
# Reemplaza los slugs y UUID con tus datos reales
ORG="acme-corp"
ZONE="bodega-1"
CAMERA_ID="uuid-de-camara"

curl "http://localhost:8003/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/status" | jq
```

#### Test de conexión de cámara:
```bash
curl -X POST "http://localhost:8003/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/test-connection" | jq
```

#### Reiniciar cámara (con rate limiting):
```bash
curl -X POST "http://localhost:8003/api/v1/orgs/$ORG/zones/$ZONE/cameras/$CAMERA_ID/restart" | jq
```

**Nota**: Si intentas reiniciar más de 3 veces en 5 minutos, recibirás error 429.

---

### 4.4 NOTIFICACIONES Y ALERTAS

#### Listar canales de notificación:
```bash
curl "http://localhost:8003/api/v1/orgs/acme-corp/notification-channels/" | jq
```

#### Crear canal de notificación EMAIL:
```bash
curl -X POST "http://localhost:8003/api/v1/orgs/acme-corp/notification-channels/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alertas Seguridad",
    "channel_type": "EMAIL",
    "config": {
      "recipients": ["security@acme.com", "ops@acme.com"],
      "from_address": "alerts@vigias.ai"
    },
    "is_active": true
  }' | jq
```

#### Crear canal SLACK:
```bash
curl -X POST "http://localhost:8003/api/v1/orgs/acme-corp/notification-channels/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Slack Alertas",
    "channel_type": "SLACK",
    "config": {
      "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL",
      "channel": "#security-alerts",
      "username": "VIGIAS-IA Bot"
    },
    "is_active": true
  }' | jq
```

#### Listar reglas de notificación:
```bash
curl "http://localhost:8003/api/v1/orgs/acme-corp/notification-rules/" | jq
```

#### Crear regla de notificación:
```bash
# Primero necesitas el UUID del canal creado arriba
CHANNEL_ID="uuid-del-canal"

curl -X POST "http://localhost:8003/api/v1/orgs/acme-corp/notification-rules/" \
  -H "Content-Type: application/json" \
  -d "{
    \"channel_id\": \"$CHANNEL_ID\",
    \"name\": \"Alertas Críticas\",
    \"description\": \"Notificar eventos críticos inmediatamente\",
    \"event_types\": [\"intrusion\", \"face_recognition\"],
    \"severities\": [\"CRITICAL\", \"HIGH\"],
    \"active_schedule\": {
      \"days\": [1,2,3,4,5],
      \"start_time\": \"18:00\",
      \"end_time\": \"08:00\"
    },
    \"cooldown_minutes\": 5,
    \"is_active\": true
  }" | jq
```

#### Ver logs de notificaciones enviadas:
```bash
curl "http://localhost:8003/api/v1/orgs/acme-corp/notification-logs/?limit=20" | jq
```

---

## 🔍 PASO 5: TESTING AVANZADO CON SWAGGER UI

### 5.1 Abrir Swagger UI:
```
http://localhost:8003/docs
```

### 5.2 Explorar secciones nuevas:

1. **Events** - Expandir y probar:
   - `GET /api/v1/orgs/{org_slug}/events/`
   - `PUT /api/v1/events/{id}/status`
   - `POST /api/v1/events/{id}/actions`

2. **Faces (Multi-tenancy)** - Probar:
   - `POST /api/v1/orgs/{org_slug}/faces/` (registrar rostro)
   - `POST /api/v1/orgs/{org_slug}/faces/search` (búsqueda facial)

3. **Camera Management** - Probar:
   - `GET /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{id}/status`
   - `POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/{id}/restart`

4. **Notifications & Alerts** - Probar:
   - `POST /api/v1/orgs/{org_slug}/notification-channels/`
   - `POST /api/v1/orgs/{org_slug}/notification-rules/`

### 5.3 Usar "Try it out" en Swagger:

1. Click en el endpoint que quieres probar
2. Click en "Try it out"
3. Llenar parámetros requeridos
4. Click en "Execute"
5. Ver la respuesta abajo

---

## 📝 PASO 6: VERIFICAR DATOS EN BASE DE DATOS

### 6.1 Conectar a PostgreSQL:
```bash
docker exec -it proyect_computer_vision_postgres_1 psql -U user -d vigias
```

### 6.2 Queries útiles:

#### Ver tablas nuevas:
```sql
\dt notification*
\dt faces

-- Salir: \q
```

#### Ver rostros registrados:
```sql
SELECT id, name, organization_id, category, created_at
FROM faces
ORDER BY created_at DESC
LIMIT 10;
```

#### Ver canales de notificación:
```sql
SELECT id, name, channel_type, organization_id, is_active
FROM notification_channels;
```

#### Ver reglas de notificación:
```sql
SELECT id, name, event_types, severities, cooldown_minutes
FROM notification_rules;
```

#### Ver estructura de tabla:
```sql
\d+ faces
\d+ notification_channels
\d+ notification_rules
```

---

## 🐛 SOLUCIÓN DE PROBLEMAS

### Problema 1: Router no inicia

**Síntomas**: `docker-compose ps` muestra router con "Exit 128" o "Exit 1"

**Solución**:
```bash
# Ver logs de error
docker-compose logs router --tail=100

# Común: Error de importación
# Fix: Verificar que todos los archivos nuevos existen
ls -la router/app/api/routes/events.py
ls -la router/app/api/routes/faces_multitenancy.py
ls -la router/app/api/routes/camera_management.py
ls -la router/app/api/routes/notification_rules.py

# Restart
docker-compose restart router
```

### Problema 2: Error 404 en nuevos endpoints

**Síntomas**: `curl http://localhost:8003/api/v1/orgs/acme-corp/faces/` retorna 404

**Solución**:
```bash
# Verificar que los routers están registrados
docker exec proyect_computer_vision_router_1 grep -r "faces_mt_router" /app/app/api/routes/__init__.py

# Verificar logs de startup
docker-compose logs router | grep "router.include"

# Restart
docker-compose restart router
```

### Problema 3: Error de conexión NATS

**Síntomas**: Logs muestran "Failed to connect to NATS"

**Solución**:
```bash
# Verificar NATS está corriendo
docker-compose ps nats

# Ver logs NATS
docker-compose logs nats --tail=50

# Restart NATS y router
docker-compose restart nats
sleep 5
docker-compose restart router
```

### Problema 4: Base de datos no tiene organizaciones

**Síntomas**: `GET /api/v1/orgs/` retorna array vacío `[]`

**Solución**:
```bash
# Crear organización de prueba
curl -X POST http://localhost:8003/api/v1/orgs/ \
  -H "Content-Type: application/json" \
  -d '{
    "slug": "test-org",
    "name": "Test Organization",
    "is_managed": false,
    "is_active": true
  }' | jq

# Verificar en BD
docker exec proyect_computer_vision_postgres_1 psql -U user -d vigias -c "SELECT slug, name FROM organizations;"
```

---

## 📊 CHECKLIST DE VERIFICACIÓN

Marca cada ítem cuando lo completes:

### Servicios:
- [ ] PostgreSQL corriendo (puerto 5436)
- [ ] Redis corriendo (puerto 6380)
- [ ] NATS corriendo (puerto 4223)
- [ ] Router corriendo (puerto 8003)

### Base de Datos:
- [x] Migración ejecutada exitosamente
- [x] Tablas `notification_*` creadas
- [x] Columnas añadidas a `faces`
- [ ] Organizaciones creadas

### Endpoints:
- [ ] `/health` retorna 200
- [ ] `/docs` carga Swagger UI
- [ ] `/api/v1/orgs/` retorna organizaciones
- [ ] `/api/v1/orgs/{slug}/faces/` retorna 200
- [ ] `/api/v1/orgs/{slug}/notification-channels/` retorna 200

### Testing Avanzado:
- [ ] Crear canal de notificación (EMAIL)
- [ ] Crear regla de notificación
- [ ] Registrar rostro de prueba
- [ ] Listar eventos (aunque esté vacío)

---

## 🚀 SIGUIENTES PASOS

Después de completar esta guía:

1. **Implementar Autenticación JWT**: Ver `IMPLEMENTACION_DIC_23_2025.md` sección "Tareas Pendientes"
2. **Integrar Inference Service**: Actualizar handlers NATS
3. **Implementar servicios de notificación**: Email, SMS, Slack, etc.
4. **Testing completo**: Ver `TESTING_GUIDE.md` para tests unitarios

---

## 📞 SOPORTE

Si encuentras problemas:
1. Revisar logs: `docker-compose logs router`
2. Verificar salud: `curl http://localhost:8003/health`
3. Consultar documentación: `AgentFiles/IMPLEMENTACION_DIC_23_2025.md`

---

**Última Actualización**: 2025-12-23
**Versión**: 1.0.0
**Testing por**: Claude Sonnet 4.5 + Logisticos Team
