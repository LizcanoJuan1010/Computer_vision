/* ARQUITECTURA DE BASE DE DATOS - PLATAFORMA DE VISIÓN ARTIFICIAL
   Motor: PostgreSQL 14+
   Optimizaciones: UUID, JSONB, Índices Compuestos para Debouncing
*/

-- 1. CONFIGURACIÓN INICIAL
CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- Para generar UUIDs v4
CREATE EXTENSION IF NOT EXISTS "vector"; -- Para embeddings de reconocimiento facial

-- Enums para mantener la integridad de los estados y evitar cadenas arbitrarias
DO $$ BEGIN
    CREATE TYPE user_role_enum AS ENUM ('ADMIN', 'OPERATOR', 'VIEWER', 'AUDITOR');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE event_status_enum AS ENUM ('PENDING', 'ACKNOWLEDGED', 'RESOLVED', 'FALSE_POSITIVE');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE event_severity_enum AS ENUM ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Función automática para actualizar el campo 'updated_at'
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$ language 'plpgsql';

-- =======================================================
-- 2. GESTIÓN DE ACCESO (RBAC) Y USUARIOS
-- =======================================================

CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(50) UNIQUE NOT NULL, -- Ej: 'SYS_ADMIN', 'SEC_GUARD'
    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_system_role BOOLEAN DEFAULT FALSE -- Roles que no se pueden borrar
);

-- Permisos granulares (Módulos)
CREATE TABLE IF NOT EXISTS permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(100) UNIQUE NOT NULL, -- Ej: 'camera:view', 'alarm:resolve', 'config:edit'
    description TEXT
);

-- Tabla Pivote Roles <-> Permisos
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id UUID REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role_id UUID REFERENCES roles(id),
    full_name VARCHAR(150),
    is_active BOOLEAN DEFAULT TRUE,
    last_login TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Trigger para updated_at en users
DROP TRIGGER IF EXISTS update_users_modtime ON users;
CREATE TRIGGER update_users_modtime BEFORE UPDATE ON users FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- =======================================================
-- 3. INFRAESTRUCTURA (ORGANIZACIONES, ZONAS, CÁMARAS)
-- =======================================================

CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    is_managed BOOLEAN DEFAULT FALSE,
    config JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS org_zones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    slug VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    location_description TEXT,
    geo_bounds JSONB, 
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(organization_id, slug)
);

CREATE TABLE IF NOT EXISTS known_faces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    embedding vector(512), -- Requires pgvector extension
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE Table IF NOT EXISTS cameras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_id UUID REFERENCES org_zones(id) ON DELETE SET NULL, -- Linked to a Zone
    name VARCHAR(100) NOT NULL,
    rtsp_url TEXT NOT NULL, 
    location_name VARCHAR(100),
    geo_location POINT,
    meta_info JSONB DEFAULT '{}'::jsonb, 
    is_active BOOLEAN DEFAULT TRUE,
    -- Added columns for Ingest service compatibility
    priority INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'UNKNOWN',
    last_seen_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Camera reconnection log for tracking connection attempts
CREATE TABLE IF NOT EXISTS camera_reconnection_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
    attempt_number INTEGER DEFAULT 1,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    reconnected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_camera_reconnection_camera ON camera_reconnection_log(camera_id);

-- =======================================================
-- 4. CEREBRO DE LA IA (CONFIGURACIÓN DE REGLAS)
-- =======================================================

/* Esta tabla es el corazón del sistema. Define qué busca cada cámara.
   Soporta simultaneidad: Una cámara puede tener una fila para 'FIRE' y otra para 'PERSON'.
*/
CREATE TABLE IF NOT EXISTS camera_ai_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
    
    -- Tipo de evento: debe coincidir con los "labels" de tus modelos de IA
    event_type VARCHAR(50) NOT NULL, -- Ej: 'person', 'fire', 'helmet', 'forklift'
    
    -- Configuración de Severidad por defecto para este evento en esta cámara
    default_severity event_severity_enum DEFAULT 'MEDIUM',
    
    -- Umbral de confianza para que la IA dispare la alerta (0.0 a 1.0)
    confidence_threshold DECIMAL(4,3) DEFAULT 0.700, 
    
    -- CRÍTICO PARA EL DEBOUNCING: Segundos para ignorar duplicados del mismo TrackID
    debounce_seconds INTEGER DEFAULT 60, 
    
    -- Zona de Interés (ROI). Si es NULL, analiza toda la imagen.
    -- Guardamos coordenadas normalizadas [0-1] o píxeles: [[x1,y1], [x2,y2], ...]
    roi_polygon JSONB, 
    
    -- Horarios activos (Ej: Solo detectar intrusos de noche). NULL = Siempre activo.
    active_schedule JSONB, -- Ej: {"start": "22:00", "end": "06:00", "days": [1,2,3,4,5]}
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- CONSTRAINT: Una cámara solo puede tener UNA configuración activa por tipo de evento
    CONSTRAINT unique_camera_event_config UNIQUE (camera_id, event_type)
);

-- =======================================================
-- 5. EVENTOS (ALARMAS)
-- =======================================================

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id UUID REFERENCES cameras(id) ON DELETE SET NULL,
    config_id UUID REFERENCES camera_ai_configs(id), -- Saber qué regla generó esto
    
    -- Datos del Motor de IA
    event_type VARCHAR(50) NOT NULL, 
    track_id VARCHAR(100), -- ID del objeto (DeepSort/ByteTrack). Vital para Debouncing.
    confidence DECIMAL(4,3),
    
    -- Evidencia (Rutas a MinIO)
    snapshot_path TEXT, -- Ej: "bucket/2023/10/cam1_person_123.jpg"
    video_clip_path TEXT, -- Ej: "bucket/2023/10/cam1_person_123.mp4"
    
    -- Datos Espaciales
    bbox JSONB, -- Bounding Box del objeto [x, y, w, h]
    
    -- Estado y Gestión
    severity event_severity_enum DEFAULT 'MEDIUM',
    status event_status_enum DEFAULT 'PENDING',
    
    -- Fechas
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- Momento de inserción
    occurred_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() -- Momento real de detección (puede variar por ms)
);

-- =======================================================
-- 6. GESTIÓN OPERATIVA Y AUDITORÍA
-- =======================================================

-- Historial de acciones sobre una alarma (Trazabilidad)
CREATE TABLE IF NOT EXISTS event_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id), -- Usuario que actuó
    
    previous_status event_status_enum,
    new_status event_status_enum,
    
    comment TEXT, -- "Falsa alarma, era un perro", "Incendio controlado"
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Auditoría General del Sistema (Quién modificó configs, quién borró usuarios)
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id), -- NULL si fue el sistema automático
    module VARCHAR(50), -- 'USER_MGMT', 'CAMERA_CONFIG', 'SYSTEM'
    action VARCHAR(50), -- 'CREATE', 'UPDATE', 'DELETE', 'LOGIN_FAILED'
    target_id UUID, -- ID del objeto afectado
    details JSONB, -- Cambios realizados (old_value, new_value)
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =======================================================
-- 7. RECONOCIMIENTO FACIAL (FACES)
-- =======================================================

CREATE TABLE IF NOT EXISTS faces (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    category VARCHAR(20) DEFAULT 'KNOWN',
    meta_info JSONB DEFAULT '{}'::jsonb,
    image_path TEXT,
    embedding vector(512),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_faces_org ON faces(organization_id);

-- Stats de Conteo (Personas entrando/saliendo)
CREATE TABLE IF NOT EXISTS camera_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
    in_count INTEGER DEFAULT 0,
    out_count INTEGER DEFAULT 0,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =======================================================
-- 8. ÍNDICES DE ALTO RENDIMIENTO (PERFORMANCE)
-- =======================================================

-- ÍNDICE 1: EL MÁS IMPORTANTE PARA TU IA (DEBOUNCING)
-- Permite buscar en milisegundos: "¿Ya vi este track_id en esta cámara hace poco?"
CREATE INDEX IF NOT EXISTS idx_events_debounce 
ON events (camera_id, event_type, track_id, occurred_at DESC);

-- ÍNDICE 2: DASHBOARD DE OPERADOR
-- Para mostrar rápidamente: "Dame las alarmas PENDING de hoy ordenadas por severidad"
CREATE INDEX IF NOT EXISTS idx_events_dashboard 
ON events (status, severity DESC, occurred_at DESC);

-- ÍNDICE 3: BÚSQUEDA POR FECHAS (REPORTES)
CREATE INDEX IF NOT EXISTS idx_events_date ON events (occurred_at);

-- ÍNDICE 4: JSONB (Para búsquedas rápidas dentro de la metadata si fuera necesario)
CREATE INDEX IF NOT EXISTS idx_cameras_meta ON cameras USING gin (meta_info);
