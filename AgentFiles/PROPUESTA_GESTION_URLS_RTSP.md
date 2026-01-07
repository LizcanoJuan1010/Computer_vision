# 📹 Propuesta: Gestión de URLs RTSP en Base de Datos

**Fecha:** 2025-12-18
**Versión:** 1.0
**Estado:** Propuesta - Pendiente de Decisión

---

## 📋 Contexto Actual

### Estado Actual del Sistema

**Configuración de Cámaras en 2 Lugares:**

1. **`ingest/cameras.json`** (Configuración del servicio Ingest)
   ```json
   {
     "id": "cam_701",
     "url": "rtsp://{USER}:{PASS}@{IP}:{PORT_RTSP}/Streaming/Channels/701",
     "name": "Bodega (2K)",
     "services": ["security"],
     "features": ["intrusion"]
   }
   ```
   - Variables reemplazadas con `.env`: `HIK_USER`, `HIK_PASS`, `HIK_IP`, `PORT_RTSP`
   - **Resultado real**: `rtsp://admin:Abc12345@192.168.1.64:554/Streaming/Channels/701`

2. **PostgreSQL** (Base de datos del Router)
   ```json
   {
     "id": "e89c7957-e75e-4802-b468-13052c1473f0",
     "name": "cam_701",
     "rtsp_url": "rtsp://placeholder",  // ⚠️ URL ficticia
     "location_name": null,
     "is_active": true
   }
   ```

### Flujo de Datos Actual

```
┌──────────────────────────────────────────────────┐
│  ingest/cameras.json (URLs REALES)               │
│  - cam_701: rtsp://admin:pass@IP:554/.../701     │
│  - cam_2201: rtsp://admin:pass@IP:554/.../2201   │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│  Ingest Service (Lee RTSP con OpenCV)            │
│  - Conecta a cámaras Hikvision directamente      │
│  - Captura frames @ 15 FPS (640x360)             │
│  - Publica a NATS: camera.{name}.frame           │
└────────────────┬─────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────┐
│  NATS Message Broker                             │
│  - Distribuye frames a suscriptores              │
└────────────────┬─────────────────────────────────┘
                 │
                 ├──────────────────────────────────┐
                 │                                  │
                 ▼                                  ▼
┌────────────────────────────┐   ┌─────────────────────────────┐
│  Inference Service         │   │  Router Service             │
│  - Procesa frames con GPU  │   │  - Streaming MJPEG          │
│  - NO usa rtsp_url de BD   │   │  - API REST                 │
└────────────────────────────┘   │  - NO usa rtsp_url de BD    │
                                 └─────────────────────────────┘
                                                 │
                                                 ▼
                                 ┌─────────────────────────────┐
                                 │  PostgreSQL                 │
                                 │  rtsp_url = "placeholder"   │
                                 │  - Solo metadata            │
                                 └─────────────────────────────┘
```

**Conclusión actual:** Las URLs RTSP reales **NO se usan** en PostgreSQL. El sistema funciona perfectamente con placeholders.

---

## 🎯 Problema a Resolver

**¿Deberíamos almacenar las URLs RTSP reales en PostgreSQL?**

### Argumentos a Favor:
- ✅ Documentación completa en un solo lugar
- ✅ Facilita debugging desde la API
- ✅ Habilita futuras funcionalidades (reconexión directa, gestión dinámica)
- ✅ Migración de cámaras entre servidores más fácil
- ✅ Auditoría y trazabilidad completa

### Argumentos en Contra:
- ⚠️ **Seguridad**: Credenciales en texto plano en BD
- ⚠️ Duplicación de configuración (`cameras.json` + PostgreSQL)
- ⚠️ Mayor complejidad sin beneficio inmediato
- ⚠️ Sistema actual funciona perfectamente

---

## 💡 Opciones Propuestas

### **Opción A: Mantener Estado Actual** ✅ Recomendado

**Descripción:**
- Mantener `rtsp_url = "rtsp://placeholder"` en PostgreSQL
- `cameras.json` sigue siendo la única fuente de URLs RTSP
- Separación de concerns clara

**Ventajas:**
- ✅ Más seguro (sin credenciales en BD)
- ✅ Sin cambios en el código actual
- ✅ Separación clara: Ingest = captura, Router = API/streaming
- ✅ Menor complejidad
- ✅ Funciona al 100%

**Desventajas:**
- ❌ Para ver URLs necesitas acceder a `cameras.json`
- ❌ No permite gestión dinámica desde la UI/API
- ❌ Duplicar cámaras manualmente en JSON y BD

**Cuándo usar:**
- Sistema en producción estable
- No se requiere gestión dinámica de cámaras
- Prioridad en seguridad

---

### **Opción B: URLs Reales con Variables de Entorno**

**Descripción:**
- Guardar URLs en formato template en PostgreSQL
- Reemplazar credenciales en runtime con variables de entorno

**Ejemplo:**
```sql
UPDATE cameras
SET rtsp_url = 'rtsp://{USER}:{PASS}@{IP}:{PORT_RTSP}/Streaming/Channels/701'
WHERE name = 'cam_701';
```

**Implementación:**
```python
# En router/app/api/routes/cameras.py
import os

def resolve_rtsp_url(template: str) -> str:
    """Resuelve variables de entorno en URL RTSP"""
    return template.format(
        USER=os.getenv('HIK_USER'),
        PASS=os.getenv('HIK_PASS'),
        IP=os.getenv('HIK_IP'),
        PORT_RTSP=os.getenv('PORT_RTSP')
    )

@router.get("/{camera_id}/rtsp-url")
async def get_camera_rtsp_url(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    """Obtiene URL RTSP resuelta con credenciales"""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    resolved_url = resolve_rtsp_url(camera.rtsp_url)
    return {"rtsp_url": resolved_url}
```

**Ventajas:**
- ✅ Credenciales NO están en BD (solo template)
- ✅ Permite ver configuración desde API
- ✅ Facilita debugging
- ✅ Sincronización con `cameras.json` más fácil

**Desventajas:**
- ⚠️ Requiere cambios en el código
- ⚠️ Duplicación de información
- ⚠️ Variables de entorno deben estar disponibles en Router

**Cuándo usar:**
- Necesitas ver configuración desde la API
- Múltiples NVRs con diferentes credenciales
- Planeas migración gradual a gestión dinámica

---

### **Opción C: Gestión Completa con Encriptación** 🔐

**Descripción:**
- Almacenar URLs completas encriptadas en PostgreSQL
- Desencriptar en runtime solo cuando se necesita
- Gestión completa desde la API REST

**Cambios en Base de Datos:**
```sql
ALTER TABLE cameras
  ADD COLUMN rtsp_url_encrypted TEXT,
  ADD COLUMN rtsp_channel VARCHAR(50);

-- Ejemplo de datos
UPDATE cameras SET
  rtsp_url_encrypted = encrypt_aes256('rtsp://admin:Abc12345@192.168.1.64:554/Streaming/Channels/701'),
  rtsp_channel = '701'
WHERE name = 'cam_701';
```

**Nuevos Endpoints:**
```python
# POST /api/v1/cameras/{id}/rtsp-config
# PUT /api/v1/cameras/{id}/rtsp-config
# GET /api/v1/cameras/{id}/rtsp-config (requiere autenticación)
# DELETE /api/v1/cameras/{id}/rtsp-config
```

**Implementación:**
```python
from cryptography.fernet import Fernet
import os

# Clave de encriptación (variable de entorno)
ENCRYPTION_KEY = os.getenv('RTSP_ENCRYPTION_KEY')
cipher = Fernet(ENCRYPTION_KEY)

def encrypt_rtsp_url(url: str) -> str:
    """Encripta URL RTSP"""
    return cipher.encrypt(url.encode()).decode()

def decrypt_rtsp_url(encrypted: str) -> str:
    """Desencripta URL RTSP"""
    return cipher.decrypt(encrypted.encode()).decode()

@router.put("/{camera_id}/rtsp-config")
async def update_camera_rtsp(
    camera_id: UUID,
    rtsp_config: RTSPConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)  # Requiere autenticación
):
    """Actualiza configuración RTSP de una cámara"""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Encriptar URL
    encrypted_url = encrypt_rtsp_url(rtsp_config.rtsp_url)
    camera.rtsp_url_encrypted = encrypted_url

    await db.commit()
    return {"status": "updated", "camera_id": camera_id}

@router.get("/{camera_id}/rtsp-config")
async def get_camera_rtsp_config(
    camera_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
    show_credentials: bool = False  # Query param
):
    """Obtiene configuración RTSP (ofuscada por defecto)"""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Desencriptar
    rtsp_url = decrypt_rtsp_url(camera.rtsp_url_encrypted)

    if not show_credentials:
        # Ofuscar credenciales: rtsp://***:***@192.168.1.64:554/...
        rtsp_url = obfuscate_credentials(rtsp_url)

    return {"rtsp_url": rtsp_url, "channel": camera.rtsp_channel}
```

**Ventajas:**
- ✅ Máxima seguridad (credenciales encriptadas)
- ✅ Gestión completa desde UI/API
- ✅ Single Source of Truth (PostgreSQL)
- ✅ Auditoría completa (cambios registrados)
- ✅ Multi-tenant (diferentes NVRs por cámara)
- ✅ Validación de conectividad antes de guardar

**Desventajas:**
- ❌ Mayor complejidad en código
- ❌ Requiere gestión de claves de encriptación
- ❌ Cambios significativos en arquitectura
- ❌ Migración de datos necesaria
- ❌ `cameras.json` quedaría obsoleto o se generaría automáticamente

**Cuándo usar:**
- Sistema con múltiples usuarios/roles
- Gestión dinámica de cámaras desde UI
- Múltiples NVRs o cámaras IP distribuidas
- Requisitos de auditoría y compliance

---

### **Opción D: Híbrido (Mejor de Ambos Mundos)** 🏆

**Descripción:**
- PostgreSQL almacena URL template + metadata
- `cameras.json` sigue siendo usado por Ingest
- Router puede consultar pero NO gestiona directamente

**Esquema de BD:**
```sql
ALTER TABLE cameras
  ADD COLUMN rtsp_template TEXT,
  ADD COLUMN rtsp_channel VARCHAR(50),
  ADD COLUMN nvr_host VARCHAR(100),
  ADD COLUMN nvr_port INTEGER DEFAULT 554;

-- Ejemplo
UPDATE cameras SET
  rtsp_template = 'rtsp://{credentials}@{host}:{port}/Streaming/Channels/{channel}',
  rtsp_channel = '701',
  nvr_host = '192.168.1.64',
  nvr_port = 554
WHERE name = 'cam_701';
```

**Endpoint de solo lectura:**
```python
@router.get("/{camera_id}/connection-info")
async def get_camera_connection_info(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    """Obtiene información de conexión (sin credenciales)"""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    return {
        "template": camera.rtsp_template,
        "channel": camera.rtsp_channel,
        "nvr_host": camera.nvr_host,
        "nvr_port": camera.nvr_port,
        "rtsp_preview": f"rtsp://***:***@{camera.nvr_host}:{camera.nvr_port}/Streaming/Channels/{camera.rtsp_channel}"
    }
```

**Ventajas:**
- ✅ Seguridad alta (sin credenciales en BD)
- ✅ Información útil para debugging
- ✅ Sin duplicación de credenciales
- ✅ `cameras.json` sigue siendo fuente de verdad
- ✅ Cambios mínimos en código actual

**Desventajas:**
- ⚠️ No permite gestión dinámica completa
- ⚠️ Metadata duplicado (pero no crítico)

**Cuándo usar:**
- Quieres mejorar visibilidad sin comprometer seguridad
- No necesitas gestión dinámica aún
- Migración gradual hacia Opción C

---

## 📊 Comparación de Opciones

| Característica | Opción A<br>(Actual) | Opción B<br>(Variables) | Opción C<br>(Encriptado) | Opción D<br>(Híbrido) |
|----------------|------------|--------------|----------------|------------|
| **Seguridad** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Facilidad de implementación** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| **Gestión dinámica** | ❌ | ⚠️ Parcial | ✅ Completa | ⚠️ Limitada |
| **Debugging** | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **Complejidad** | ⭐ Baja | ⭐⭐ Media | ⭐⭐⭐⭐ Alta | ⭐⭐ Media |
| **Auditoría** | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Costo de mantenimiento** | ⭐ Bajo | ⭐⭐ Medio | ⭐⭐⭐⭐ Alto | ⭐⭐ Medio |
| **Riesgo de cambio** | ✅ Ninguno | ⚠️ Bajo | ⚠️ Alto | ⚠️ Bajo |

---

## 🚀 Recomendación Final

### **Para el Estado Actual: Opción A (No cambiar)** ✅

**Razones:**
1. El sistema funciona al 100% actualmente
2. No hay requisito inmediato de gestión dinámica
3. Máxima seguridad sin complejidad adicional
4. Separación de concerns es correcta arquitectónicamente

### **Para Futuro (6-12 meses): Opción D → Opción C**

**Ruta de migración sugerida:**

```
Estado Actual (Opción A)
         ↓
    [3-6 meses]
         ↓
Opción D (Híbrido) - Agregar metadata sin credenciales
         ↓
    [6-12 meses]
         ↓
Opción C (Encriptado) - Gestión completa desde UI
```

**Hitos sugeridos:**

1. **Fase 1 (Actual):** Mantener como está
2. **Fase 2 (Q2 2025):** Implementar Opción D si se requiere mejor debugging
3. **Fase 3 (Q3-Q4 2025):** Evaluar Opción C si se desarrolla UI de gestión

---

## 🛠️ Plan de Implementación (Si se aprueba Opción D)

### **Paso 1: Migración de Base de Datos**
```sql
-- Agregar columnas nuevas
ALTER TABLE cameras
  ADD COLUMN rtsp_template TEXT,
  ADD COLUMN rtsp_channel VARCHAR(50),
  ADD COLUMN nvr_host VARCHAR(100),
  ADD COLUMN nvr_port INTEGER DEFAULT 554;

-- Migrar datos desde cameras.json
UPDATE cameras SET
  rtsp_template = 'rtsp://{credentials}@{host}:{port}/Streaming/Channels/{channel}',
  rtsp_channel = '701',
  nvr_host = '192.168.1.64',
  nvr_port = 554
WHERE name = 'cam_701';

UPDATE cameras SET
  rtsp_template = 'rtsp://{credentials}@{host}:{port}/Streaming/Channels/{channel}',
  rtsp_channel = '2201',
  nvr_host = '192.168.1.64',
  nvr_port = 554
WHERE name = 'cam_2201';
```

### **Paso 2: Actualizar Schemas Pydantic**
```python
# router/app/api/routes/schemas_extended.py

class CameraConnectionInfo(BaseModel):
    """Información de conexión (sin credenciales)"""
    rtsp_template: Optional[str] = None
    rtsp_channel: Optional[str] = None
    nvr_host: Optional[str] = None
    nvr_port: Optional[int] = 554
    rtsp_preview: str  # URL ofuscada

class CameraResponse(CameraBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    connection_info: Optional[CameraConnectionInfo] = None

    class Config:
        from_attributes = True
```

### **Paso 3: Agregar Endpoint**
```python
# router/app/api/routes/cameras.py

@router.get("/{camera_id}/connection-info", response_model=CameraConnectionInfo)
async def get_camera_connection_info(camera_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    Obtiene información de conexión RTSP (sin credenciales).

    Útil para debugging y documentación.
    """
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    rtsp_preview = None
    if camera.rtsp_template and camera.nvr_host:
        rtsp_preview = f"rtsp://***:***@{camera.nvr_host}:{camera.nvr_port}/Streaming/Channels/{camera.rtsp_channel}"

    return CameraConnectionInfo(
        rtsp_template=camera.rtsp_template,
        rtsp_channel=camera.rtsp_channel,
        nvr_host=camera.nvr_host,
        nvr_port=camera.nvr_port,
        rtsp_preview=rtsp_preview
    )
```

### **Paso 4: Testing**
```bash
# Probar nuevo endpoint
curl http://localhost:8003/api/v1/cameras/e89c7957-e75e-4802-b468-13052c1473f0/connection-info

# Respuesta esperada:
{
  "rtsp_template": "rtsp://{credentials}@{host}:{port}/Streaming/Channels/{channel}",
  "rtsp_channel": "701",
  "nvr_host": "192.168.1.64",
  "nvr_port": 554,
  "rtsp_preview": "rtsp://***:***@192.168.1.64:554/Streaming/Channels/701"
}
```

### **Paso 5: Documentación**
- Actualizar `README.md` con nuevos endpoints
- Agregar ejemplos en Swagger UI
- Documentar en `CHANGELOG.md`

---

## 📝 Notas Adicionales

### Consideraciones de Seguridad

1. **Nunca loggear URLs completas** con credenciales
2. **Ofuscar en logs:**
   ```python
   logger.info(f"Connecting to {obfuscate_url(rtsp_url)}")
   # Output: "Connecting to rtsp://***:***@192.168.1.64:554/..."
   ```
3. **Variables de entorno cifradas** en producción
4. **Permisos de BD:** Solo admin puede leer `rtsp_url_encrypted`

### Dependencias

Si se implementa Opción C (encriptación):
```bash
pip install cryptography
```

```python
# requirements.txt
cryptography>=41.0.0
```

### Variables de Entorno Necesarias

```bash
# .env
HIK_USER=admin
HIK_PASS=Abc12345
HIK_IP=192.168.1.64
PORT_RTSP=554
PORT_HTTP=80

# Solo para Opción C
RTSP_ENCRYPTION_KEY=<generar con: Fernet.generate_key()>
```

---

## 📅 Cronograma Sugerido (Si se aprueba)

| Fase | Duración | Actividades |
|------|----------|-------------|
| **Análisis** | 1 semana | Revisar propuesta, decidir opción |
| **Diseño** | 1 semana | Diseño de BD, endpoints, schemas |
| **Implementación** | 2 semanas | Código, migración, testing |
| **Testing** | 1 semana | QA, pruebas de integración |
| **Deploy** | 1 semana | Staging → Producción |
| **Total** | **6 semanas** | |

---

## ✅ Decisión Pendiente

**Pregunta clave:** ¿Necesitamos gestión dinámica de cámaras desde la UI en los próximos 6 meses?

- **Si NO:** Mantener Opción A (actual)
- **Si SÍ (parcial):** Implementar Opción D (híbrido)
- **Si SÍ (completo):** Planear Opción C (encriptado)

---

**Documento creado por:** Claude Sonnet 4.5
**Última actualización:** 2025-12-18
**Revisión pendiente:** Usuario
