-- Migration script to add missing columns to existing databases
-- Run this AFTER the database already has tables
-- Safe to run multiple times (uses IF NOT EXISTS patterns)

-- Add missing columns to cameras table
DO $$ 
BEGIN
    -- Add priority column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'cameras' AND column_name = 'priority') THEN
        ALTER TABLE cameras ADD COLUMN priority INTEGER DEFAULT 0;
        RAISE NOTICE 'Added priority column to cameras';
    END IF;
    
    -- Add status column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'cameras' AND column_name = 'status') THEN
        ALTER TABLE cameras ADD COLUMN status VARCHAR(50) DEFAULT 'UNKNOWN';
        RAISE NOTICE 'Added status column to cameras';
    END IF;
    
    -- Add last_seen_at column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'cameras' AND column_name = 'last_seen_at') THEN
        ALTER TABLE cameras ADD COLUMN last_seen_at TIMESTAMP WITH TIME ZONE;
        RAISE NOTICE 'Added last_seen_at column to cameras';
    END IF;
    
    -- Add target_fps column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'cameras' AND column_name = 'target_fps') THEN
        ALTER TABLE cameras ADD COLUMN target_fps REAL DEFAULT 15.0;
        RAISE NOTICE 'Added target_fps column to cameras';
    END IF;
    
    -- Add max_reconnects column if it doesn't exist
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'cameras' AND column_name = 'max_reconnects') THEN
        ALTER TABLE cameras ADD COLUMN max_reconnects INTEGER DEFAULT 5;
        RAISE NOTICE 'Added max_reconnects column to cameras';
    END IF;
    
    -- Add features column if it doesn't exist (for face, lpr, intrusion detection)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name = 'cameras' AND column_name = 'features') THEN
        ALTER TABLE cameras ADD COLUMN features JSONB DEFAULT '["face", "lpr", "intrusion", "line_crossing"]'::jsonb;
        RAISE NOTICE 'Added features column to cameras';
    END IF;
    
    -- Ensure existing cameras have features enabled
    UPDATE cameras 
    SET features = '["face", "lpr", "intrusion", "line_crossing"]'::jsonb 
    WHERE features IS NULL OR features = '{}'::jsonb OR features = '[]'::jsonb;
    
END $$;

-- Create camera_reconnection_log table if it doesn't exist
CREATE TABLE IF NOT EXISTS camera_reconnection_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
    attempt_number INTEGER DEFAULT 1,
    success BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    reconnected_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_camera_reconnection_camera ON camera_reconnection_log(camera_id);

-- Verify the migration
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'cameras' 
ORDER BY ordinal_position;
