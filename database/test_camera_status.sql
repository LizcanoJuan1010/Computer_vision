-- ============================================================
-- Camera Status Testing & Verification Queries
-- ============================================================

-- 1. VERIFICAR ESTADO GENERAL DE CÁMARAS
-- ============================================================
SELECT
    name,
    status,
    is_active,
    priority,
    target_fps,
    current_fps,
    connection_attempts,
    last_seen_at,
    last_error
FROM cameras
ORDER BY last_seen_at DESC NULLS LAST;

-- 2. CÁMARAS ONLINE (Funcionando bien)
-- ============================================================
SELECT
    name,
    status,
    last_seen_at,
    CASE
        WHEN last_seen_at > NOW() - INTERVAL '30 seconds' THEN '✅ ACTIVA'
        WHEN last_seen_at > NOW() - INTERVAL '5 minutes' THEN '⚠️  RECIENTE'
        ELSE '❌ INACTIVA'
    END as health_status,
    EXTRACT(EPOCH FROM (NOW() - last_seen_at)) as seconds_since_last_frame
FROM cameras
WHERE status = 'ONLINE'
ORDER BY last_seen_at DESC;

-- 3. CÁMARAS CON PROBLEMAS
-- ============================================================
SELECT
    name,
    status,
    connection_attempts,
    last_error,
    last_error_at,
    last_seen_at
FROM cameras
WHERE status IN ('ERROR', 'OFFLINE')
ORDER BY last_error_at DESC NULLS LAST;

-- 4. HISTORIAL DE RECONEXIONES (Últimas 20)
-- ============================================================
SELECT
    c.name,
    r.attempt_number,
    r.success,
    r.error_message,
    r.attempted_at,
    CASE
        WHEN r.success THEN '✅'
        ELSE '❌'
    END as result
FROM camera_reconnection_log r
JOIN cameras c ON r.camera_id = c.id
ORDER BY r.attempted_at DESC
LIMIT 20;

-- 5. TASA DE ÉXITO DE CONEXIONES POR CÁMARA
-- ============================================================
SELECT
    c.name,
    COUNT(*) as total_attempts,
    SUM(CASE WHEN r.success THEN 1 ELSE 0 END) as successful,
    SUM(CASE WHEN NOT r.success THEN 1 ELSE 0 END) as failed,
    ROUND(100.0 * SUM(CASE WHEN r.success THEN 1 ELSE 0 END) / COUNT(*), 2) as success_rate_percent
FROM camera_reconnection_log r
JOIN cameras c ON r.camera_id = c.id
WHERE r.attempted_at > NOW() - INTERVAL '24 hours'
GROUP BY c.name
ORDER BY success_rate_percent DESC;

-- 6. MÉTRICAS DE SALUD (Health Metrics - Últimas 10)
-- ============================================================
SELECT
    c.name,
    h.measured_at,
    h.fps,
    h.frames_captured,
    h.frames_dropped,
    ROUND(100.0 * h.frames_dropped / NULLIF(h.frames_captured, 0), 2) as drop_rate_percent,
    h.latency_ms,
    h.status
FROM camera_health_metrics h
JOIN cameras c ON h.camera_id = c.id
ORDER BY h.measured_at DESC
LIMIT 10;

-- 7. RESUMEN EJECUTIVO - DASHBOARD
-- ============================================================
SELECT
    COUNT(*) FILTER (WHERE status = 'ONLINE') as online,
    COUNT(*) FILTER (WHERE status = 'OFFLINE') as offline,
    COUNT(*) FILTER (WHERE status = 'ERROR') as error,
    COUNT(*) FILTER (WHERE status = 'MAINTENANCE') as maintenance,
    COUNT(*) FILTER (WHERE is_active = true) as total_active,
    COUNT(*) FILTER (WHERE last_seen_at > NOW() - INTERVAL '1 minute') as recently_active,
    ROUND(AVG(connection_attempts), 2) as avg_connection_attempts
FROM cameras;

-- 8. CÁMARAS QUE NECESITAN ATENCIÓN
-- ============================================================
SELECT
    name,
    status,
    connection_attempts,
    CASE
        WHEN connection_attempts >= max_reconnect_attempts THEN '🚨 MAX ATTEMPTS REACHED'
        WHEN connection_attempts >= max_reconnect_attempts * 0.7 THEN '⚠️  CLOSE TO LIMIT'
        ELSE '✅ OK'
    END as reconnection_status,
    last_error,
    last_seen_at
FROM cameras
WHERE connection_attempts > 0
ORDER BY connection_attempts DESC;

-- 9. TEST: OBTENER IDs PARA PROBAR EN BROWSER
-- ============================================================
SELECT
    id,
    name,
    status,
    'http://localhost:8003/stream/' || id || '/snapshot' as snapshot_url,
    'http://localhost:8003/stream/' || id as stream_url,
    'http://localhost:8003/stream/annotate/' || id as annotated_url
FROM cameras
WHERE is_active = true AND status = 'ONLINE'
LIMIT 5;

-- 10. VERIFICAR CONFIGURACIÓN DE RECONEXIÓN
-- ============================================================
SELECT
    name,
    max_reconnect_attempts,
    reconnect_interval_seconds,
    CONCAT(reconnect_interval_seconds, ' segundos') as reconnect_interval_display,
    priority,
    target_fps
FROM cameras
ORDER BY priority DESC, name;

-- ============================================================
-- QUERIES DE MANTENIMIENTO
-- ============================================================

-- Resetear contadores de conexión para todas las cámaras
-- UPDATE cameras SET connection_attempts = 0 WHERE connection_attempts > 0;

-- Poner cámara en mantenimiento
-- UPDATE cameras SET status = 'MAINTENANCE' WHERE id = 'CAMERA_ID_AQUI';

-- Remover mantenimiento y forzar OFFLINE (para que ingest reintente)
-- UPDATE cameras SET status = 'OFFLINE', connection_attempts = 0 WHERE id = 'CAMERA_ID_AQUI';

-- Limpiar logs antiguos de reconexión (más de 7 días)
-- DELETE FROM camera_reconnection_log WHERE attempted_at < NOW() - INTERVAL '7 days';

-- Limpiar métricas antiguas (más de 30 días)
-- DELETE FROM camera_health_metrics WHERE measured_at < NOW() - INTERVAL '30 days';
