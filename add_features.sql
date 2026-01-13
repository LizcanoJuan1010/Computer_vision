ALTER TABLE cameras ADD COLUMN IF NOT EXISTS features JSONB DEFAULT '["face", "lpr", "intrusion", "line_crossing"]'::jsonb;
UPDATE cameras SET features = '["face", "lpr", "intrusion", "line_crossing"]'::jsonb WHERE features IS NULL OR features::text = '{}'::text;
SELECT id, name, features FROM cameras;
