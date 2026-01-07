# 📘 Guía para Desarrollador Frontend - VIGIAS-IA

## Documento Técnico para Integración con Backend

**Versión:** 1.0  
**Fecha:** 2025-12-19  
**Sistema:** VIGIAS-IA con Multi-Tenancy

---

## 📋 Índice

1. [Arquitectura General](#arquitectura-general)
2. [Cómo se Consumen las Cámaras](#cómo-se-consumen-las-cámaras)
3. [Cómo Funciona el Backend](#cómo-funciona-el-backend)
4. [Rol de Miniconda3 (Servicio de IA)](#rol-de-miniconda3-servicio-de-ia)
5. [Todos los Endpoints Disponibles](#todos-los-endpoints-disponibles)
6. [Cómo Llega Todo al Frontend](#cómo-llega-todo-al-frontend)
7. [Ejemplos de Integración](#ejemplos-de-integración)

---

## 🏗️ Arquitectura General

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              VIGIAS-IA System                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐    RTSP    ┌─────────────┐    NATS    ┌─────────────┐   │
│   │  Cámaras    │───────────▶│   Ingest    │───────────▶│  Inference  │   │
│   │  Hikvision  │            │   (Go)      │            │  (Python)   │   │
│   │             │            │   :8081     │            │  :5000      │   │
│   └─────────────┘            └─────────────┘            └──────┬──────┘   │
│                                                                 │          │
│                                                         MJPEG Stream       │
│                                                                 │          │
│   ┌─────────────┐            ┌─────────────┐            ┌──────▼──────┐   │
│   │  PostgreSQL │◀──────────▶│   Router    │◀───────────│  Frontend   │   │
│   │   :5436     │            │  (FastAPI)  │  REST/WS   │   (React)   │   │
│   └─────────────┘            │   :8003     │            └─────────────┘   │
│                              └──────┬──────┘                               │
│   ┌─────────────┐                   │                                      │
│   │    Redis    │◀──────────────────┘                                      │
│   │   :6380     │                                                          │
│   └─────────────┘                                                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Resumen de Servicios

| Servicio | Puerto | Tecnología | Función |
|----------|--------|------------|---------|
| **Router** | 8003 | FastAPI (Python) | API REST principal + WebSocket |
| **Inference** | 5000 | Python + CUDA | Procesamiento IA + Streaming video |
| **Ingest** | 8081 | Go | Captura de video RTSP |
| **NATS** | 4223 | Message Broker | Cola de mensajes interna |
| **PostgreSQL** | 5436 | Base de datos | Persistencia |
| **Redis** | 6380 | Cache | Configuración en memoria |

---

## 📹 Cómo se Consumen las Cámaras

### Flujo Completo de Video

```
Cámara ──▶ Ingest ──▶ NATS ──▶ Inference ──▶ Frontend
 RTSP       Decode     Pub/Sub    IA          MJPEG
```

### Paso 1: Configuración de Cámaras

Las cámaras se configuran en el archivo `ingest/cameras.json`:

```json
{
  "id": "cam_701",
  "org_slug": "vigias-local",
  "zone_slug": "zona-default",
  "url": "rtsp://user:pass@192.168.1.100:554/Streaming/Channels/701",
  "name": "Bodega Principal",
  "services": ["security"],
  "features": ["intrusion", "face"]
}
```

### Paso 2: Captura por Ingest (Go)

El servicio **Ingest** (escrito en Go):
1. Lee `cameras.json` al iniciar
2. Conecta a cada cámara vía **RTSP**
3. Decodifica el stream H.264 con FFmpeg
4. Aplica filtro de movimiento (MOG2) para ahorrar procesamiento
5. Redimensiona a 640x360 píxeles
6. Codifica como JPEG
7. Publica en NATS con el subject:
   ```
   org.{org_slug}.zone.{zone_slug}.camera.{camera_id}.frame
   ```
   Ejemplo: `org.vigias-local.zone.zona-default.camera.cam_701.frame`

### Paso 3: Procesamiento por Inference (Python)

El servicio **Inference** (Python con GPU):
1. Se suscribe a NATS: `camera.*.frame` (wildcard)
2. Recibe frames JPEG
3. Ejecuta modelos de IA:
   - **YOLO v8**: Detección de objetos/personas
   - **InsightFace**: Reconocimiento facial
   - **LPR**: Lectura de placas
4. Aplica análisis espacial (zonas de intrusión, líneas de cruce)
5. Genera alarmas si hay detecciones
6. Almacena frames anotados en memoria
7. Los sirve vía HTTP en el endpoint `/debug/{camera_id}/mjpeg`

### Paso 4: Consumo por Frontend

El frontend puede consumir el video de dos formas:

#### Opción A: Stream MJPEG con IA (Recomendado)
```html
<img src="http://localhost:5000/debug/cam_701/mjpeg" alt="Stream con IA">
```
- ✅ Incluye bounding boxes de detecciones
- ✅ Muestra zonas de intrusión
- ✅ ~15 FPS
- ⚠️ Formato MJPEG (no H.264)

#### Opción B: Stream Raw (sin IA)
```html
<img src="http://localhost:8081/stream/cam_701" alt="Stream raw">
```
- ✅ Menor latencia
- ❌ Sin anotaciones de IA

---

## ⚙️ Cómo Funciona el Backend

### Router Service (FastAPI) - Puerto 8003

Es el **punto de entrada principal** para el frontend. Maneja:

1. **API REST**: CRUD de cámaras, usuarios, alarmas
2. **WebSocket**: Notificaciones en tiempo real
3. **Autenticación** (futuro): JWT tokens

#### Arquitectura Interna

```
┌─────────────────────────────────────────────────────────────┐
│                      Router (FastAPI)                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐ │
│   │   Routes     │    │   Services   │    │    Models    │ │
│   │  /api/v1/*   │───▶│  Business    │───▶│  SQLAlchemy  │ │
│   │              │    │  Logic       │    │              │ │
│   └──────────────┘    └──────────────┘    └──────────────┘ │
│          │                   │                   │          │
│          ▼                   ▼                   ▼          │
│   ┌──────────────────────────────────────────────────────┐ │
│   │                     Cache Layer                       │ │
│   │   L1 (TTLCache in-memory) ◀──▶ L2 (Redis)            │ │
│   └──────────────────────────────────────────────────────┘ │
│          │                                                  │
│          ▼                                                  │
│   ┌──────────────┐              ┌──────────────┐           │
│   │  PostgreSQL  │              │     NATS     │           │
│   │  (Datos)     │              │  (Eventos)   │           │
│   └──────────────┘              └──────────────┘           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### Estructura de Archivos

```
router/
├── app/
│   ├── main.py              # Punto de entrada FastAPI
│   ├── models.py            # Modelos SQLAlchemy (ORM)
│   ├── schemas.py           # Schemas Pydantic (validación)
│   ├── core/
│   │   ├── config.py        # Configuración (env vars)
│   │   └── database.py      # Conexión PostgreSQL
│   ├── api/
│   │   └── routes/
│   │       ├── cameras.py   # CRUD cámaras + zonas AI
│   │       ├── faces.py     # Gestión de rostros
│   │       ├── alarms.py    # Historial de alarmas
│   │       ├── streaming.py # Proxy de streams
│   │       └── general.py   # Health, users, roles
│   └── services/
│       ├── cache.py         # Redis + L1 cache
│       ├── dispatcher.py    # Procesa frames de NATS
│       └── multitenancy_utils.py  # Helpers multi-tenant
└── Dockerfile
```

---

## 🐍 Rol de Miniconda3 (Servicio de IA)

### ¿Por qué Miniconda?

El servicio de **Inference** requiere:
- Python 3.10+
- PyTorch con soporte CUDA
- Bibliotecas de IA pesadas (ultralytics, insightface)
- Dependencias específicas de versión

**Miniconda** permite crear un entorno aislado con todas estas dependencias sin afectar el sistema.

### Ubicación del Entorno

```
/home/logisticos-two/dev/miniconda3/envs/vigias-ia/
```

### Activación Manual

```bash
source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia
```

### Dependencias Principales

| Paquete | Versión | Uso |
|---------|---------|-----|
| torch | 2.x | Deep Learning framework |
| ultralytics | 8.x | YOLO v8 object detection |
| insightface | 0.7+ | Face recognition |
| onnxruntime-gpu | 1.16+ | Inference acelerado |
| nats-py | 2.x | Cliente NATS |
| aiohttp | 3.x | Servidor HTTP async |
| opencv-python | 4.x | Procesamiento de imagen |

### Cómo Ejecuta el Inference

```bash
# El servicio se ejecuta FUERA de Docker para acceso a GPU
cd /home/logisticos-two/dev/Proyect_Computer_Vision
source /home/logisticos-two/dev/miniconda3/bin/activate vigias-ia
python -c "from inference.main import run; import asyncio; asyncio.run(run())"
```

### Arquitectura del Inference

```
inference/
├── main.py              # Punto de entrada
├── config.py            # Configuración
├── database.py          # Conexión a PostgreSQL
├── loader.py            # Carga de caras (blacklist)
├── models/
│   ├── yolo.py          # YOLO v8 (detección)
│   ├── face.py          # InsightFace (reconocimiento)
│   └── lpr.py           # License Plate Recognition
└── processors/
    └── security.py      # Pipeline de procesamiento
```

### GPU Acceleration

```python
# inference/models/yolo.py
self.model = pt_model.to('cuda')  # Carga en GPU
result = self.model(frame, half=True)  # Inferencia FP16
```

El servicio detecta automáticamente la GPU disponible (NVIDIA) y ejecuta:
- YOLO en CUDA con FP16 (half precision)
- InsightFace con CUDAExecutionProvider
- LPR con aceleración GPU

---

## 📡 Todos los Endpoints Disponibles

### Base URLs

| Servicio | Base URL |
|----------|----------|
| **Router API** | `http://localhost:8003` |
| **Inference Streams** | `http://localhost:5000` |
| **Swagger Docs** | `http://localhost:8003/docs` |

---

### 🔐 Sistema y Salud

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/health` | Health check con estado de servicios |
| GET | `/api/v1/system/summary` | Conteo de entidades |

**Ejemplo Response `/health`:**
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
    "l1_max": 1000,
    "l1_ttl": 60
  }
}
```

---

### 🏢 Organizaciones (Multi-Tenancy)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/orgs` | Listar todas las organizaciones |
| POST | `/api/v1/orgs` | Crear organización |
| GET | `/api/v1/orgs/{slug}` | Obtener organización |
| PUT | `/api/v1/orgs/{slug}` | Actualizar organización |
| DELETE | `/api/v1/orgs/{slug}` | Eliminar organización |

**Request Body (POST):**
```json
{
  "slug": "mi-empresa",
  "name": "Mi Empresa S.A.",
  "is_managed": false
}
```

---

### 📍 Zonas (Dentro de Organización)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/orgs/{org_slug}/zones` | Listar zonas |
| POST | `/api/v1/orgs/{org_slug}/zones` | Crear zona |
| GET | `/api/v1/orgs/{org_slug}/zones/{zone_slug}` | Obtener zona |
| PUT | `/api/v1/orgs/{org_slug}/zones/{zone_slug}` | Actualizar zona |
| DELETE | `/api/v1/orgs/{org_slug}/zones/{zone_slug}` | Eliminar zona |

**Request Body (POST):**
```json
{
  "slug": "bodega-principal",
  "name": "Bodega Principal",
  "location_description": "Entrada norte del edificio"
}
```

---

### 📹 Cámaras

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/cameras/` | Listar todas las cámaras |
| POST | `/api/v1/cameras/` | Crear cámara |
| GET | `/api/v1/cameras/{id}` | Obtener cámara por UUID |
| PUT | `/api/v1/cameras/{id}` | Actualizar cámara |
| DELETE | `/api/v1/cameras/{id}` | Eliminar cámara |

**Request Body (POST):**
```json
{
  "name": "Cámara Entrada",
  "rtsp_url": "rtsp://user:pass@192.168.1.100:554/stream",
  "location_name": "Entrada principal",
  "zone_id": "91b428cb-30c1-400c-b49f-2a007484fc9a",
  "is_active": true
}
```

**Response:**
```json
{
  "id": "f55a7d08-651f-43e1-992b-7a9f5112b2c8",
  "name": "Cámara Entrada",
  "rtsp_url": "rtsp://...",
  "location_name": "Entrada principal",
  "zone_id": "91b428cb-30c1-400c-b49f-2a007484fc9a",
  "meta_info": {},
  "is_active": true,
  "created_at": "2025-12-19T15:00:00Z",
  "updated_at": "2025-12-19T15:00:00Z"
}
```

---

### 🎯 Zonas de IA (Reglas por Cámara)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/cameras/{id}/zones` | Listar zonas AI de cámara |
| POST | `/api/v1/cameras/{id}/zones` | Crear zona AI (polígono) |
| PUT | `/api/v1/cameras/{id}/zones/{zone_id}` | Actualizar zona AI |
| DELETE | `/api/v1/cameras/{id}/zones/{zone_id}` | Eliminar zona AI |

**Request Body (POST) - Zona de Intrusión:**
```json
{
  "event_type": "intrusion",
  "roi_polygon": [
    [0.1, 0.2],
    [0.9, 0.2],
    [0.9, 0.8],
    [0.1, 0.8]
  ],
  "confidence_threshold": 0.5,
  "debounce_seconds": 60,
  "default_severity": "HIGH"
}
```

> ⚠️ **Importante**: Las coordenadas del polígono están **normalizadas** (0.0 a 1.0) donde:
> - (0,0) = esquina superior izquierda
> - (1,1) = esquina inferior derecha

---

### 👤 Rostros (Blacklist)

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/faces/` | Listar rostros registrados |
| POST | `/api/v1/faces/` | Registrar nuevo rostro |
| DELETE | `/api/v1/faces/{id}` | Eliminar rostro |

**Request (POST) - Multipart Form:**
```
POST /api/v1/faces/
Content-Type: multipart/form-data

name: "Juan Perez"
file: [imagen.jpg]
```

**Response:**
```json
{
  "status": "success",
  "id": 5,
  "message": "Did register Juan Perez"
}
```

---

### 🚨 Alarmas/Eventos

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/v1/alarms/` | Listar alarmas |
| GET | `/api/v1/alarms/{id}` | Obtener alarma |
| PUT | `/api/v1/alarms/{id}/status` | Cambiar estado |

**Query Parameters (GET):**
```
?status=PENDING
&severity=HIGH
&camera_id=f55a7d08-...
&limit=50
&offset=0
```

**Response:**
```json
[
  {
    "id": "a1b2c3d4-...",
    "camera_id": "f55a7d08-...",
    "event_type": "intrusion",
    "track_id": "123",
    "confidence": 0.85,
    "severity": "HIGH",
    "status": "PENDING",
    "snapshot_path": "/evidence/2025/12/19/...",
    "occurred_at": "2025-12-19T15:30:00Z"
  }
]
```

**Estados posibles:**
- `PENDING` - Nueva alarma
- `ACKNOWLEDGED` - Vista por operador
- `RESOLVED` - Resuelta
- `FALSE_POSITIVE` - Falsa alarma

---

### 🎥 Streaming de Video

| Puerto | Método | Endpoint | Descripción |
|--------|--------|----------|-------------|
| 5000 | GET | `/debug/{camera_id}/mjpeg` | Stream con anotaciones IA |
| 8081 | GET | `/stream/{camera_id}` | Stream raw (sin IA) |
| 8081 | GET | `/snapshot/{camera_id}` | Imagen estática |

**IDs de Cámaras Disponibles:**
```
cam_701
cam_1001
cam_1301
cam_2201
cam_2701
```

**Ejemplo HTML:**
```html
<img src="http://localhost:5000/debug/cam_701/mjpeg" 
     style="width: 640px; height: 360px;"
     alt="Stream con IA">
```

---

### 🔔 WebSocket (Tiempo Real)

| Endpoint | Descripción |
|----------|-------------|
| `ws://localhost:8003/ws/notifications` | Alarmas en tiempo real |

**Conexión JavaScript:**
```javascript
const ws = new WebSocket('ws://localhost:8003/ws/notifications');

ws.onmessage = (event) => {
  const alarm = JSON.parse(event.data);
  console.log('Nueva alarma:', alarm);
  // {
  //   "type": "ALARM_TRIGGERED",
  //   "data": {
  //     "event_type": "intrusion",
  //     "camera_id": "cam_701",
  //     "track_id": "123",
  //     "severity": "HIGH",
  //     "timestamp": 1702999800
  //   }
  // }
};

ws.onopen = () => console.log('Conectado a WebSocket');
ws.onclose = () => console.log('WebSocket cerrado');
ws.onerror = (e) => console.error('Error WebSocket:', e);
```

---

### 🛠️ Administración

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/admin/cache/warmup` | Calentar cache Redis |
| GET | `/api/v1/permissions` | CRUD permisos |
| GET | `/api/v1/roles` | CRUD roles |
| GET | `/api/v1/users` | CRUD usuarios |

---

## 🖥️ Cómo Llega Todo al Frontend

### Diagrama de Flujo Completo

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             FRONTEND (React)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                        Componentes UI                                │  │
│   │                                                                      │  │
│   │   ┌───────────────┐  ┌───────────────┐  ┌───────────────┐          │  │
│   │   │ CameraGrid    │  │ AlarmPanel    │  │ FaceManager   │          │  │
│   │   │               │  │               │  │               │          │  │
│   │   │ <img src=     │  │ useWebSocket  │  │ POST /faces   │          │  │
│   │   │  "...:5000/   │  │  ws://:8003/  │  │               │          │  │
│   │   │   debug/...   │  │   ws/notif..  │  │               │          │  │
│   │   │   /mjpeg">    │  │               │  │               │          │  │
│   │   └───────────────┘  └───────────────┘  └───────────────┘          │  │
│   │                                                                      │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                              │         │         │                         │
│                              ▼         ▼         ▼                         │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                     Capa de Servicios                                │  │
│   │                                                                      │  │
│   │   api.js                │   websocket.js     │   config.js          │  │
│   │   - fetch('/api/v1/')   │   - WebSocket()    │   - API_BASE_URL     │  │
│   │   - axios.get()         │   - reconnect      │   - STREAM_URL       │  │
│   │                                                                      │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │     HTTP / WS         │
                    └───────────┬───────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   :8003 (Router)              :5000 (Inference)              :8081 (Ingest)│
│   ┌─────────────┐             ┌─────────────┐                ┌───────────┐ │
│   │ REST API    │             │ MJPEG       │                │ Raw       │ │
│   │ WebSocket   │             │ Stream      │                │ Stream    │ │
│   │             │             │ + IA        │                │           │ │
│   └─────────────┘             └─────────────┘                └───────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### URLs por Entorno

| Entorno | Router API | Inference Stream |
|---------|------------|------------------|
| Desarrollo | `http://localhost:8003` | `http://localhost:5000` |
| Producción | `https://api.vigias.io` | `https://stream.vigias.io` |

### Configuración Sugerida (React)

```javascript
// config.js
export const config = {
  // Desarrollo
  API_BASE_URL: process.env.REACT_APP_API_URL || 'http://localhost:8003',
  STREAM_BASE_URL: process.env.REACT_APP_STREAM_URL || 'http://localhost:5000',
  WS_URL: process.env.REACT_APP_WS_URL || 'ws://localhost:8003',
};
```

### Ejemplo: Hook de Cámaras

```javascript
// hooks/useCameras.js
import { useState, useEffect } from 'react';
import { config } from '../config';

export function useCameras() {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch(`${config.API_BASE_URL}/api/v1/cameras/`)
      .then(res => res.json())
      .then(data => {
        setCameras(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err);
        setLoading(false);
      });
  }, []);

  const getStreamUrl = (cameraId) => {
    return `${config.STREAM_BASE_URL}/debug/${cameraId}/mjpeg`;
  };

  return { cameras, loading, error, getStreamUrl };
}
```

### Ejemplo: Componente de Stream

```jsx
// components/CameraStream.jsx
import React from 'react';
import { config } from '../config';

export function CameraStream({ cameraId, width = 640, height = 360 }) {
  const streamUrl = `${config.STREAM_BASE_URL}/debug/${cameraId}/mjpeg`;
  
  return (
    <div className="camera-stream">
      <img 
        src={streamUrl}
        alt={`Camera ${cameraId}`}
        width={width}
        height={height}
        style={{ 
          objectFit: 'cover',
          borderRadius: '8px'
        }}
      />
      <div className="camera-label">{cameraId}</div>
    </div>
  );
}
```

### Ejemplo: WebSocket para Alarmas

```jsx
// hooks/useAlarms.js
import { useState, useEffect, useCallback } from 'react';
import { config } from '../config';

export function useAlarms() {
  const [alarms, setAlarms] = useState([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`${config.WS_URL}/ws/notifications`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const alarm = JSON.parse(event.data);
      if (alarm.type === 'ALARM_TRIGGERED') {
        setAlarms(prev => [alarm.data, ...prev].slice(0, 100));
        
        // Opcional: Notificación del navegador
        if (Notification.permission === 'granted') {
          new Notification('Nueva Alarma', {
            body: `${alarm.data.event_type} en ${alarm.data.camera_id}`,
            icon: '/alarm-icon.png'
          });
        }
      }
    };

    return () => ws.close();
  }, []);

  return { alarms, connected };
}
```

---

## 💡 Ejemplos de Integración

### Dashboard de Cámaras (Grid)

```jsx
import { useCameras } from '../hooks/useCameras';
import { CameraStream } from '../components/CameraStream';

export function CameraDashboard() {
  const { cameras, loading, getStreamUrl } = useCameras();

  if (loading) return <div>Cargando cámaras...</div>;

  return (
    <div style={{ 
      display: 'grid', 
      gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
      gap: '16px' 
    }}>
      {cameras.map(camera => (
        <CameraStream 
          key={camera.id} 
          cameraId={camera.name}  // Usar name como ID para stream
        />
      ))}
    </div>
  );
}
```

### Panel de Alarmas en Tiempo Real

```jsx
import { useAlarms } from '../hooks/useAlarms';

export function AlarmPanel() {
  const { alarms, connected } = useAlarms();

  return (
    <div className="alarm-panel">
      <div className="status">
        WebSocket: {connected ? '🟢 Conectado' : '🔴 Desconectado'}
      </div>
      
      <ul className="alarm-list">
        {alarms.map((alarm, idx) => (
          <li key={idx} className={`alarm severity-${alarm.severity.toLowerCase()}`}>
            <span className="time">
              {new Date(alarm.timestamp * 1000).toLocaleTimeString()}
            </span>
            <span className="type">{alarm.event_type}</span>
            <span className="camera">{alarm.camera_id}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

---

## 📝 Notas Importantes

1. **CORS**: El backend permite requests desde cualquier origen en desarrollo. En producción, configurar `CORS_ORIGINS` en variables de entorno.

2. **Trailing Slash**: La mayoría de endpoints requieren trailing slash (`/api/v1/cameras/` no `/api/v1/cameras`).

3. **UUIDs**: Los IDs de cámaras en la BD son UUIDs, pero el streaming usa los IDs de `cameras.json` (como `cam_701`).

4. **Autenticación**: Por implementar. Actualmente no hay autenticación en los endpoints.

5. **Rate Limiting**: No implementado. Considerar para producción.

---

## 📞 Contacto

Si tienes dudas sobre la integración, contactar al equipo de backend.
