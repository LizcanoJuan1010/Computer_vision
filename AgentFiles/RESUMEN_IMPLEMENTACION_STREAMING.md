# RESUMEN: STREAMING CON SLUGS + GUÍA FRONTEND

**Fecha**: 2025-12-26
**Sprint**: 1 Day 1 (continuación)
**Cambios**: Streaming user-friendly + Documentación completa

---

## ✅ CAMBIOS IMPLEMENTADOS

### 1. Endpoints de Streaming Mejorados (Puerto 5000)

#### Antes:
```
GET /debug/{camera-uuid}/mjpeg
❌ Requiere conocer el UUID de la cámara
❌ No user-friendly
```

#### Ahora:
```
✅ GET /debug/{camera-uuid}/mjpeg
   (Mantiene compatibilidad)

✅ GET /stream/{org_slug}/{zone_slug}/{camera_name}/mjpeg
   (NUEVO - user-friendly con slugs)

✅ GET /cameras
   (NUEVO - lista todas las cámaras con URLs de stream)

✅ GET /health
   (Health check para Docker)
```

### Ejemplos de Uso:

**Opción 1 - Por UUID** (más rápido):
```
http://localhost:5000/debug/52d65193-806a-420a-a197-7160fcc412b9/mjpeg
```

**Opción 2 - Por Slugs** (más legible):
```
http://localhost:5000/stream/vigias/planta/cam701/mjpeg
```

**Opción 3 - Listar cámaras disponibles**:
```bash
curl http://localhost:5000/cameras

# Response:
{
  "cameras": [
    {
      "id": "52d65193-806a-420a-a197-7160fcc412b9",
      "name": "Bodega (2K) - CAM701",
      "org": "vigias",
      "zone": "planta",
      "stream_urls": {
        "by_uuid": "/debug/52d65193.../mjpeg",
        "by_slug": "/stream/vigias/planta/bodega-2k-cam701/mjpeg"
      }
    }
  ]
}
```

---

### 2. Lógica de Resolución de Nombres

El endpoint `/stream/{org}/{zone}/{name}/mjpeg` busca la cámara por:

1. **Slug exacto** del nombre (convertido a lowercase, sin espacios)
2. **Partial match** case-insensitive en el nombre
3. **UUID directo** si se pasa como nombre

Ejemplo:
```
Input: "cam701"
Match: "Bodega (2K) - CAM701"  ✅

Input: "bodega"
Match: "Bodega (2K) - CAM701"  ✅

Input: "52d65193-806a-420a-a197-7160fcc412b9"
Match: Camera con ese UUID  ✅
```

---

### 3. Dockerización (Preparado pero no activo)

Se creó `inference/Dockerfile` para dockerizar el servicio, pero **NO está activo** porque:

❌ NVIDIA Container Toolkit no configurado correctamente
❌ GPU no accesible desde Docker

**Estado actual**:
- Inference corre con **Python + Miniconda** (GPU disponible)
- Docker-compose tiene la configuración lista (comentada)

**Para activar Docker** (futuro):
1. Configurar NVIDIA Container Toolkit
2. Reiniciar Docker daemon
3. Descomentar `vision-inference` en docker-compose.yml
4. `docker-compose up -d vision-inference`

---

### 4. Documentación Completa para Frontend

Se creó **`GUIA_INTEGRACION_FRONTEND.md`** con:

✅ Arquitectura del sistema completa
✅ Estructura multi-tenant (slugs vs UUIDs)
✅ Todos los endpoints disponibles con ejemplos
✅ Flujos de integración típicos (Dashboard, Registro, Eventos)
✅ Código de ejemplo React/Vue
✅ Troubleshooting común
✅ Mejores prácticas

**Ubicación**:
```
/Proyect_Computer_Vision/GUIA_INTEGRACION_FRONTEND.md
```

---

## 🔧 ARCHIVOS MODIFICADOS

```
M  inference/main.py                     # Nuevos endpoints de streaming
A  inference/Dockerfile                  # Docker (preparado)
M  docker-compose.yml                    # Puerto 5000 + volúmenes
A  GUIA_INTEGRACION_FRONTEND.md          # Documentación frontend
A  AgentFiles/RESUMEN_IMPLEMENTACION_STREAMING.md  # Este archivo
```

---

## 📊 COMPARACIÓN: ANTES vs AHORA

| Aspecto | Antes | Ahora |
|---------|-------|-------|
| **Stream URL** | Solo UUID | UUID + Slugs |
| **Descubrimiento** | Manual | Endpoint `/cameras` |
| **Frontend Docs** | ❌ Ninguna | ✅ Guía completa |
| **User-friendly** | ❌ Difícil | ✅ Fácil |
| **Dockerizado** | ❌ No | ⚠️ Preparado |

---

## 🎯 PRÓXIMOS PASOS

### Para Backend:
- [ ] Configurar NVIDIA Container Toolkit (opcional)
- [ ] Sprint 1 Day 2: Auto-save UNKNOWN en zonas restringidas
- [ ] Sprint 1 Day 3-4: Endpoints de blacklist management

### Para Frontend:
- [ ] Leer `GUIA_INTEGRACION_FRONTEND.md`
- [ ] Implementar componente de stream con slugs
- [ ] Dashboard de cámaras en grid
- [ ] Panel de eventos en tiempo real

---

## 🚀 CÓMO USAR DESDE EL FRONTEND

### Setup SSH Tunnel (desde tu casa):

```bash
ssh -L 8003:localhost:8003 \
    -L 5000:localhost:5000 \
    usuario@IP_OFICINA
```

### Listar Cámaras Disponibles:

```javascript
const cameras = await fetch('http://localhost:5000/cameras')
  .then(r => r.json());

console.log(cameras);
// {
//   cameras: [...],
//   total: 5
// }
```

### Mostrar Stream:

```html
<!-- Opción 1: Por UUID -->
<img src="http://localhost:5000/debug/52d65193.../mjpeg" />

<!-- Opción 2: Por Slug (MÁS FÁCIL) -->
<img src="http://localhost:5000/stream/vigias/planta/cam701/mjpeg" />
```

### React Component Completo:

```jsx
function CameraGrid() {
  const [cameras, setCameras] = useState([]);

  useEffect(() => {
    fetch('http://localhost:5000/cameras')
      .then(res => res.json())
      .then(data => setCameras(data.cameras));
  }, []);

  return (
    <div className="grid">
      {cameras.map(cam => (
        <div key={cam.id}>
          <h3>{cam.name}</h3>
          <img src={`http://localhost:5000${cam.stream_urls.by_slug}`} />
        </div>
      ))}
    </div>
  );
}
```

---

## 📝 NOTAS PARA EL FRONT-END ENGINEER

1. **Multitenancy es obligatorio**
   - Todas las APIs usan estructura `org/zone/camera`
   - NO crear slugs manualmente - usar los que retorna la API

2. **CORS está habilitado**
   - No hay problema con peticiones desde localhost:3000

3. **Rate Limiting**
   - API Gateway: 100 req/min
   - Para desarrollo: usar puerto 8003 directo (bypass gateway)

4. **Streaming**
   - Formato MJPEG (compatible con `<img>` tag)
   - Anotaciones incluidas (bounding boxes, nombres)
   - FPS: 120 (muy fluido)

5. **Autenticación** (futuro)
   - Actualmente SIN autenticación
   - Sprint 6 agregará JWT vía Keycloak

---

## 🐛 TROUBLESHOOTING RÁPIDO

**Stream no carga (404)**:
```bash
# 1. Verificar que inference esté corriendo
curl http://localhost:5000/health

# 2. Listar cámaras disponibles
curl http://localhost:5000/cameras

# 3. Verificar que la cámara esté activa
curl http://localhost:8003/api/v1/orgs/vigias/zones/planta/cameras/
```

**CORS Error**:
```javascript
// Asegurarse de usar el puerto correcto
const API_URL = "http://localhost:8003";  // ✅ Correcto
const API_URL = "http://localhost:8000";  // ❌ Incorrecto
```

**Slugs vs UUIDs**:
- Organizations/Zones → **slugs** (legibles)
- Cameras/Events → **UUIDs** (técnicos)
- Streams → **ambos soportados**

---

**Última actualización**: 2025-12-26 20:30
**Autor**: Backend Team
**Revisar**: `GUIA_INTEGRACION_FRONTEND.md` para más detalles
