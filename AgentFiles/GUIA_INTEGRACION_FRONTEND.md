# GUÍA DE INTEGRACIÓN FRONTEND - VIGIAS-IA v2.0

**Para**: Front-End Engineer
**Fecha**: 2025-12-26
**Versión**: Sprint 1 Day 1

---

## 📋 ÍNDICE

1. [Arquitectura del Sistema](#arquitectura-del-sistema)
2. [Estructura Multi-Tenant (Slugs)](#estructura-multi-tenant)
3. [Endpoints Disponibles](#endpoints-disponibles)
4. [Flujos de Integración](#flujos-de-integración)
5. [Streaming de Video](#streaming-de-video)
6. [Ejemplos de Código](#ejemplos-de-código)
7. [Troubleshooting](#troubleshooting)

---

## 🏗️ ARQUITECTURA DEL SISTEMA

```
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (React/Vue/etc)                    │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    API GATEWAY (Puerto 8080)                     │
│  Enrutamiento, Autenticación, Rate Limiting                     │
└─────────────────────────────────────────────────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
    ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
    │ Identity MS  │   │   Org MS     │   │   Ops MS     │
    │ (Port 8083)  │   │ (Port 8084)  │   │ (Port 8085)  │
    └──────────────┘   └──────────────┘   └──────────────┘
                          │
                          ▼
         ┌────────────────────────────────────────┐
         │   VISION AI ROUTER (Puerto 8003)       │
         │   - Cámaras, Zonas, Rostros, Eventos   │
         └────────────────────────────────────────┘
                          │
                          ▼
         ┌────────────────────────────────────────┐
         │  INFERENCE SERVICE (Puerto 5000)       │
         │  - Stream MJPEG con detecciones        │
         │  - YOLO + InsightFace + LPR            │
         └────────────────────────────────────────┘
```

### Puertos Importantes:

| Puerto | Servicio | Uso Frontend |
|--------|----------|--------------|
| **8080** | API Gateway | ✅ **Punto de entrada principal** (producción) |
| **8003** | Vision AI Router | ✅ Desarrollo directo (bypass gateway) |
| **5000** | Inference Stream | ✅ **Video streaming con detecciones** |
| 8761 | Eureka (Service Discovery) | ❌ Solo interno |
| 8888 | Config Server | ❌ Solo interno |

---

## 🏢 ESTRUCTURA MULTI-TENANT

### Jerarquía de Datos:

```
Organization (org_slug)
  └── Zone (zone_slug)
       └── Camera (camera_uuid)
            ├── Events
            ├── AI Config
            └── RTSP Stream
```

### Identificadores:

| Entidad | Identificador | Ejemplo | Notas |
|---------|--------------|---------|-------|
| **Organization** | `slug` (string) | `"vigias"`, `"claro-sas"` | Único, URL-friendly |
| **Zone** | `slug` (string) | `"planta"`, `"entrada"` | Único dentro de org |
| **Camera** | `id` (UUID) | `"52d65193-806a-420a-a197-7160fcc412b9"` | UUID v4 |
| **Face** | `id` (integer) | `123` | Auto-increment |
| **Event** | `id` (UUID) | `"7f8a9b2c-..."` | UUID v4 |

⚠️ **IMPORTANTE**:
- Organizations y Zones usan **slugs** (legibles)
- Cameras, Events, Faces usan **UUIDs/IDs**
- NO crear slugs manualmente - usar los que retorna la API

---

## 🔌 ENDPOINTS DISPONIBLES

### BASE URLs:

```javascript
// Producción (a través del Gateway)
const API_GATEWAY = "http://localhost:8080";

// Desarrollo (directo al servicio)
const VISION_API = "http://localhost:8003";
const INFERENCE_API = "http://localhost:5000";
```

---

### 1️⃣ ORGANIZACIONES

#### `GET /api/v1/orgs/`
Listar todas las organizaciones.

**Request:**
```bash
curl http://localhost:8003/api/v1/orgs/
```

**Response:**
```json
{
  "organizations": [
    {
      "id": "a1b2c3d4-...",
      "slug": "vigias",
      "name": "VIGIAS Seguridad",
      "is_active": true,
      "created_at": "2025-01-15T10:00:00Z"
    },
    {
      "id": "e5f6g7h8-...",
      "slug": "claro-sas",
      "name": "Claro Colombia",
      "is_active": true,
      "created_at": "2025-01-16T11:00:00Z"
    }
  ],
  "total": 2
}
```

#### `POST /api/v1/orgs/`
Crear organización.

**Request:**
```json
{
  "name": "Mi Empresa",
  "slug": "mi-empresa",
  "is_managed": false,
  "config": {}
}
```

---

### 2️⃣ ZONAS

#### `GET /api/v1/orgs/{org_slug}/zones/`
Listar zonas de una organización.

**Request:**
```bash
curl http://localhost:8003/api/v1/orgs/vigias/zones/
```

**Response:**
```json
{
  "zones": [
    {
      "id": "zone-uuid-1",
      "slug": "planta",
      "name": "Planta de Producción",
      "organization_id": "org-uuid",
      "is_restricted_zone": true,
      "auto_save_unknown": true,
      "polygon": [[x1,y1], [x2,y2], ...],
      "camera_count": 5
    }
  ]
}
```

#### `POST /api/v1/orgs/{org_slug}/zones/`
Crear zona.

**Request:**
```json
{
  "name": "Almacén Principal",
  "slug": "almacen",
  "is_restricted_zone": false,
  "auto_save_unknown": false,
  "polygon": [[0,0], [100,0], [100,100], [0,100]]
}
```

---

### 3️⃣ CÁMARAS

#### `GET /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/`
Listar cámaras de una zona.

**Request:**
```bash
curl http://localhost:8003/api/v1/orgs/vigias/zones/planta/cameras/
```

**Response:**
```json
{
  "cameras": [
    {
      "id": "52d65193-806a-420a-a197-7160fcc412b9",
      "name": "Bodega (2K) - CAM701",
      "zone_id": "zone-uuid",
      "rtsp_url": "rtsp://...",
      "is_active": true,
      "priority": "HIGH",
      "location_name": "Esquina NE",
      "stream_url": "/stream/vigias/planta/bodega-2k-cam701/mjpeg"
    }
  ]
}
```

#### `POST /api/v1/orgs/{org_slug}/zones/{zone_slug}/cameras/`
Crear cámara.

**Request:**
```json
{
  "name": "Cámara Entrada Principal",
  "rtsp_url": "rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/101",
  "location_name": "Entrada Principal",
  "priority": "CRITICAL"
}
```

**Response:**
```json
{
  "id": "new-camera-uuid",
  "name": "Cámara Entrada Principal",
  "zone_id": "zone-uuid",
  "created_at": "2025-12-26T20:00:00Z"
}
```

---

### 4️⃣ CONFIGURACIÓN AI DE CÁMARA

#### `GET /api/v1/cameras/{camera_id}/config`
Obtener configuración AI (desde Redis).

**Response:**
```json
{
  "camera_id": "camera-uuid",
  "org_id": "org-uuid",
  "intrusion_detection": true,
  "face_recognition": true,
  "lpr_detection": false,
  "face_threshold": 0.85,
  "debounce_intrusion": 3.0,
  "roi_polygon": [[x1,y1], [x2,y2], ...]
}
```

#### `PUT /api/v1/cameras/{camera_id}/config`
Actualizar configuración.

**Request:**
```json
{
  "face_recognition": true,
  "face_threshold": 0.90,
  "intrusion_detection": false
}
```

---

### 5️⃣ ROSTROS (Face Recognition)

#### `GET /api/v1/orgs/{org_slug}/faces/`
Listar rostros registrados.

**Query params:**
- `?category=KNOWN` - Solo personas conocidas
- `?category=BLACKLIST` - Solo blacklist
- `?shared_global=true` - Solo blacklist global compartida

**Response:**
```json
{
  "faces": [
    {
      "id": 123,
      "name": "Juan Pérez",
      "category": "KNOWN",
      "organization_id": "org-uuid",
      "share_to_global_blacklist": false,
      "created_at": "2025-12-26T10:00:00Z"
    }
  ]
}
```

#### `POST /api/v1/orgs/{org_slug}/faces/`
Registrar rostro.

**Request:**
```json
{
  "name": "María González",
  "category": "KNOWN",
  "image_base64": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "share_to_global_blacklist": false
}
```

**Response:**
```json
{
  "id": 124,
  "name": "María González",
  "category": "KNOWN",
  "embedding": [0.123, 0.456, ...],
  "created_at": "2025-12-26T20:10:00Z"
}
```

#### `POST /api/v1/faces/{face_id}/share-to-global`
Compartir a blacklist global.

**Request:**
```json
{
  "reason": "Individuo involucrado en múltiples robos"
}
```

---

### 6️⃣ EVENTOS (Alarmas)

#### `GET /api/v1/events/`
Listar eventos recientes.

**Query params:**
- `?org_slug=vigias`
- `?event_type=intrusion`
- `?severity=HIGH`
- `?start_date=2025-12-26T00:00:00Z`
- `?limit=50`

**Response:**
```json
{
  "events": [
    {
      "id": "event-uuid",
      "camera_id": "camera-uuid",
      "event_type": "intrusion",
      "severity": "HIGH",
      "track_id": 1,
      "confidence": 0.95,
      "bbox": [100, 200, 300, 400],
      "snapshot_path": "/evidence/vigias/event-uuid.jpg",
      "created_at": "2025-12-26T20:15:30Z"
    }
  ]
}
```

#### `GET /api/v1/cameras/{camera_id}/events/recent`
Eventos recientes de una cámara específica.

---

### 7️⃣ NOTIFICACIONES

#### `GET /api/v1/notifications/`
Listar notificaciones.

**Query params:**
- `?user_id=user-uuid`
- `?is_read=false`

**Response:**
```json
{
  "notifications": [
    {
      "id": "notif-uuid",
      "user_id": "user-uuid",
      "title": "Intrusión detectada",
      "message": "Persona no autorizada en Bodega Principal",
      "severity": "HIGH",
      "is_read": false,
      "event_id": "event-uuid",
      "created_at": "2025-12-26T20:15:30Z"
    }
  ]
}
```

#### `PUT /api/v1/notifications/{notif_id}/status`
Marcar como leída.

**Request:**
```json
{
  "is_read": true
}
```

---

## 🎥 STREAMING DE VIDEO

### Inference Service (Puerto 5000)

#### Endpoints de Stream:

1. **Por UUID (directo)**:
```
GET http://localhost:5000/debug/{camera-uuid}/mjpeg
```

2. **Por Slug (user-friendly)** ⭐ NUEVO:
```
GET http://localhost:5000/stream/{org_slug}/{zone_slug}/{camera_name}/mjpeg
```

Ejemplo:
```
http://localhost:5000/stream/vigias/planta/cam701/mjpeg
```

3. **Listar cámaras disponibles**:
```
GET http://localhost:5000/cameras
```

**Response:**
```json
{
  "cameras": [
    {
      "id": "52d65193-806a-420a-a197-7160fcc412b9",
      "name": "Bodega (2K) - CAM701",
      "org": "vigias",
      "zone": "planta",
      "is_active": true,
      "has_rtsp": true,
      "stream_urls": {
        "by_uuid": "/debug/52d65193-806a-420a-a197-7160fcc412b9/mjpeg",
        "by_slug": "/stream/vigias/planta/bodega-2k-cam701/mjpeg"
      }
    }
  ],
  "total": 5
}
```

### Integración en Frontend:

#### React/Vue Component:

```jsx
// Componente de Video Stream
function CameraStream({ cameraId, orgSlug, zoneSlug, cameraName }) {
  // Opción 1: Por UUID (más rápido)
  const streamUrlUUID = `http://localhost:5000/debug/${cameraId}/mjpeg`;

  // Opción 2: Por Slug (más legible)
  const streamUrlSlug = `http://localhost:5000/stream/${orgSlug}/${zoneSlug}/${cameraName}/mjpeg`;

  return (
    <div className="camera-stream">
      <h3>{cameraName}</h3>
      <img
        src={streamUrlSlug}
        alt={`Stream ${cameraName}`}
        style={{width: '100%', maxWidth: '640px'}}
      />
    </div>
  );
}
```

#### Grid de Múltiples Cámaras:

```jsx
function CameraGrid() {
  const [cameras, setCameras] = useState([]);

  useEffect(() => {
    // Obtener lista de cámaras
    fetch('http://localhost:5000/cameras')
      .then(res => res.json())
      .then(data => setCameras(data.cameras));
  }, []);

  return (
    <div className="camera-grid">
      {cameras.map(cam => (
        <div key={cam.id} className="camera-card">
          <h4>{cam.name}</h4>
          <p>{cam.org} / {cam.zone}</p>
          <img
            src={`http://localhost:5000${cam.stream_urls.by_slug}`}
            alt={cam.name}
          />
        </div>
      ))}
    </div>
  );
}
```

---

## 🔄 FLUJOS DE INTEGRACIÓN TÍPICOS

### Flujo 1: Dashboard de Monitoreo

```javascript
// 1. Obtener organizaciones
const orgs = await fetch('/api/v1/orgs/').then(r => r.json());

// 2. Seleccionar org y obtener zonas
const zones = await fetch(`/api/v1/orgs/${orgSlug}/zones/`).then(r => r.json());

// 3. Obtener cámaras de una zona
const cameras = await fetch(`/api/v1/orgs/${orgSlug}/zones/${zoneSlug}/cameras/`)
  .then(r => r.json());

// 4. Mostrar streams
cameras.forEach(cam => {
  const streamUrl = `http://localhost:5000/debug/${cam.id}/mjpeg`;
  // Renderizar <img src={streamUrl} />
});
```

### Flujo 2: Registro de Persona

```javascript
// 1. Capturar foto (desde cámara o upload)
const photoFile = document.getElementById('photoInput').files[0];

// 2. Convertir a base64
const reader = new FileReader();
reader.onload = async () => {
  const base64 = reader.result;

  // 3. Enviar a API
  const response = await fetch(`/api/v1/orgs/${orgSlug}/faces/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: "Juan Pérez",
      category: "KNOWN",
      image_base64: base64,
      share_to_global_blacklist: false
    })
  });

  const data = await response.json();
  console.log('Rostro registrado:', data.id);
};
reader.readAsDataURL(photoFile);
```

### Flujo 3: Panel de Eventos en Tiempo Real

```javascript
// Opción A: Polling (cada 5 segundos)
setInterval(async () => {
  const events = await fetch('/api/v1/events/?org_slug=vigias&limit=10')
    .then(r => r.json());

  updateEventsUI(events);
}, 5000);

// Opción B: WebSocket (TODO - Sprint 3)
// const ws = new WebSocket('ws://localhost:8003/ws/events');
// ws.onmessage = (msg) => {
//   const event = JSON.parse(msg.data);
//   showNotification(event);
// };
```

---

## 🛠️ TROUBLESHOOTING

### Problema: CORS Error

**Error**: `Access to fetch at 'http://localhost:8003' from origin 'http://localhost:3000' has been blocked by CORS policy`

**Solución**:
El backend ya tiene CORS habilitado. Verifica que estés usando el puerto correcto (8003 para Vision API).

Si persiste, agregar en tu código:
```javascript
fetch(url, {
  mode: 'cors',
  credentials: 'include'
})
```

---

### Problema: Stream no carga (404 Not Found)

**Posibles causas**:

1. **Cámara inactiva**: Verificar `is_active = true`
```bash
curl http://localhost:8003/api/v1/orgs/vigias/zones/planta/cameras/
```

2. **Inference service no corriendo**:
```bash
# Verificar
curl http://localhost:5000/health

# Si no responde, iniciar
cd Proyect_Computer_Vision
python -m inference.main
```

3. **UUID incorrecto**: Usar endpoint `/cameras` para obtener la lista correcta
```bash
curl http://localhost:5000/cameras
```

---

### Problema: Slugs vs UUIDs confusos

**Regla simple**:
- **Slugs**: Organizations, Zones → URLs legibles (`/orgs/vigias/zones/planta`)
- **UUIDs**: Cameras, Events, Faces → IDs técnicos (`/cameras/52d65193-...`)

**Para streams**, ahora puedes usar ambos:
```
✅ /stream/vigias/planta/cam701/mjpeg  (slug)
✅ /debug/52d65193-806a-420a-a197-7160fcc412b9/mjpeg  (uuid)
```

---

### Problema: Imagen en stream se ve borrosa

**Causas**:
1. **JPEG quality bajo**: Configurado en 96 (muy buena calidad)
2. **Redimensionamiento en frontend**: Usar `object-fit: contain` en CSS

```css
.camera-stream img {
  width: 100%;
  height: auto;
  object-fit: contain;
  max-width: 1280px;
}
```

---

## 📚 RECURSOS ADICIONALES

- **Swagger UI**: http://localhost:8003/docs
- **Eureka Dashboard**: http://localhost:8761/
- **Plan de Desarrollo**: `/AgentFiles/PLAN_DESARROLLO_PRODUCCION.md`
- **Cambios Sprint 1**: `/AgentFiles/CAMBIOS_SPRINT1_DAY1.md`

---

## ⚠️ NOTAS IMPORTANTES

1. **NO modificar docker-compose.yml del proyecto Proyect_Computer_Vision**
   - Usar el docker-compose.yml del nivel superior (`/dev/docker-compose.yml`)

2. **Multitenancy es OBLIGATORIO**
   - Todas las consultas deben incluir `org_slug` o `org_id`
   - Las zonas son únicas por organización

3. **Streams en HTTPS**
   - Para producción, usar reverse proxy (Nginx/Caddy)
   - El stream MJPEG no soporta HTTPS directamente

4. **Rate Limiting**
   - API Gateway limita a 100 req/min por IP
   - Para desarrollo, bypass usar puerto 8003 directo

5. **Autenticación** (Pendiente - Sprint 6)
   - Actualmente SIN autenticación (desarrollo)
   - En producción usará JWT vía Keycloak

---

**Última actualización**: 2025-12-26
**Versión**: Sprint 1 Day 1
**Autor**: Backend Team (Claude + Logisticos)

¿Dudas? Revisar `/AgentFiles/` o preguntar al equipo de backend.
