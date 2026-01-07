-- ============================================================
-- Migration 005: Stream Management & Health Monitoring
-- Sprint 2: Gestión de Streams RTSP
-- Created: 2025-12-30
-- ============================================================

-- Purpose: Add fields for camera status tracking, health monitoring,
-- and priority-based resource management

BEGIN;

-- ============================================================
-- Part 1: Camera Status & Health Tracking
-- ============================================================

-- Add status enum type
DO $$ BEGIN
    CREATE TYPE camera_status AS ENUM ('ONLINE', 'OFFLINE', 'MAINTENANCE', 'ERROR');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Add status and health tracking fields to cameras table
ALTER TABLE cameras
    ADD COLUMN IF NOT EXISTS status camera_status DEFAULT 'OFFLINE',
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_frame_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS connection_attempts INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_error TEXT,
    ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMP WITH TIME ZONE;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_cameras_status ON cameras(status);
CREATE INDEX IF NOT EXISTS idx_cameras_last_seen ON cameras(last_seen_at);

-- ============================================================
-- Part 2: Priority & Resource Management
-- ============================================================

-- Add priority enum type
DO $$ BEGIN
    CREATE TYPE camera_priority AS ENUM ('LOW', 'NORMAL', 'HIGH', 'CRITICAL');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Add priority and resource management fields
ALTER TABLE cameras
    ADD COLUMN IF NOT EXISTS priority camera_priority DEFAULT 'NORMAL',
    ADD COLUMN IF NOT EXISTS target_fps DECIMAL(5,2) DEFAULT 30.0,
    ADD COLUMN IF NOT EXISTS current_fps DECIMAL(5,2),
    ADD COLUMN IF NOT EXISTS fps_degraded BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS max_reconnect_attempts INTEGER DEFAULT 12,
    ADD COLUMN IF NOT EXISTS reconnect_interval_seconds INTEGER DEFAULT 300; -- 5 minutes

-- Add index for priority-based queries
CREATE INDEX IF NOT EXISTS idx_cameras_priority ON cameras(priority, status);

-- ============================================================
-- Part 3: Stream Health Metrics
-- ============================================================

-- Create table for historical stream health metrics
CREATE TABLE IF NOT EXISTS camera_health_metrics (
    id SERIAL PRIMARY KEY,
    camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    measured_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    fps DECIMAL(5,2),
    frames_captured BIGINT,
    frames_dropped BIGINT,
    latency_ms INTEGER,
    cpu_percent DECIMAL(5,2),
    gpu_percent DECIMAL(5,2),
    memory_mb INTEGER,
    status camera_status,
    CONSTRAINT fk_camera_health_camera FOREIGN KEY (camera_id) REFERENCES cameras(id) ON DELETE CASCADE
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_camera_health_camera ON camera_health_metrics(camera_id, measured_at DESC);
CREATE INDEX IF NOT EXISTS idx_camera_health_time ON camera_health_metrics(measured_at DESC);

-- ============================================================
-- Part 4: Reconnection Attempts Log
-- ============================================================

-- Create table to track reconnection attempts
CREATE TABLE IF NOT EXISTS camera_reconnection_log (
    id SERIAL PRIMARY KEY,
    camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    attempted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    attempt_number INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    reconnected_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER
);

-- Index for recent attempts
CREATE INDEX IF NOT EXISTS idx_reconnection_camera ON camera_reconnection_log(camera_id, attempted_at DESC);

-- ============================================================
-- Part 5: Helper Functions
-- ============================================================

-- Function to update camera last_seen timestamp
CREATE OR REPLACE FUNCTION update_camera_last_seen()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE cameras
    SET last_seen_at = NOW(),
        last_frame_at = NOW(),
        status = CASE
            WHEN status = 'OFFLINE' THEN 'ONLINE'::camera_status
            ELSE status
        END,
        connection_attempts = 0
    WHERE id = NEW.camera_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update last_seen when health metrics are inserted
DROP TRIGGER IF EXISTS trigger_update_camera_last_seen ON camera_health_metrics;
CREATE TRIGGER trigger_update_camera_last_seen
    AFTER INSERT ON camera_health_metrics
    FOR EACH ROW
    EXECUTE FUNCTION update_camera_last_seen();

-- ============================================================
-- Part 6: Default Values for Existing Cameras
-- ============================================================

-- Update existing cameras with default values
UPDATE cameras
SET
    status = 'ONLINE'::camera_status,
    priority = 'NORMAL'::camera_priority,
    target_fps = 30.0,
    max_reconnect_attempts = 12,
    reconnect_interval_seconds = 300
WHERE status IS NULL;

-- ============================================================
-- Part 7: Comments & Documentation
-- ============================================================

COMMENT ON COLUMN cameras.status IS 'Current connection status: ONLINE, OFFLINE, MAINTENANCE, ERROR';
COMMENT ON COLUMN cameras.last_seen_at IS 'Last time the camera sent any data';
COMMENT ON COLUMN cameras.last_frame_at IS 'Last time a frame was successfully processed';
COMMENT ON COLUMN cameras.priority IS 'Priority for resource allocation: LOW, NORMAL, HIGH, CRITICAL';
COMMENT ON COLUMN cameras.target_fps IS 'Target frames per second for this camera';
COMMENT ON COLUMN cameras.current_fps IS 'Actual measured FPS';
COMMENT ON COLUMN cameras.fps_degraded IS 'True if FPS was reduced due to resource constraints';
COMMENT ON COLUMN cameras.max_reconnect_attempts IS 'Maximum reconnection attempts before giving up';
COMMENT ON COLUMN cameras.reconnect_interval_seconds IS 'Seconds between reconnection attempts';

COMMENT ON TABLE camera_health_metrics IS 'Historical stream health and performance metrics';
COMMENT ON TABLE camera_reconnection_log IS 'Log of all reconnection attempts for debugging';

COMMIT;

-- ============================================================
-- Verification Queries
-- ============================================================

-- List all cameras with their new status
-- SELECT id, name, status, priority, target_fps, last_seen_at FROM cameras;

-- Check recent health metrics
-- SELECT * FROM camera_health_metrics ORDER BY measured_at DESC LIMIT 10;

-- Check reconnection attempts
-- SELECT * FROM camera_reconnection_log ORDER BY attempted_at DESC LIMIT 10;
