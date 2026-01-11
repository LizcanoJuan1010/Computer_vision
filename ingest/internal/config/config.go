package config

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

type CameraConfig struct {
	ID                 string                 `json:"id"`
	OrgSlug            string                 `json:"org_slug"`   // Multi-tenancy: organization slug
	ZoneSlug           string                 `json:"zone_slug"`  // Multi-tenancy: zone slug
	URL                string                 `json:"url"`
	Name               string                 `json:"name"`
	Services           []string               `json:"services"`
	Features           []string               `json:"features"`
	Zones              map[string]interface{} `json:"zones"`
	FaceConfig         map[string]interface{} `json:"face_config"`
	IntrusionConfig    map[string]interface{} `json:"intrusion_config"`
	LineCrossingConfig map[string]interface{} `json:"line_crossing_config"`
	YoloConfig         map[string]interface{} `json:"yolo_config"`
	// Additional internal fields
	OrgID       string `json:"org_id,omitempty"`
	ZoneID      string `json:"zone_id,omitempty"`
	Priority    string `json:"priority,omitempty"`     // FPS Priority: LOW, NORMAL, HIGH, CRITICAL
	ResizeWidth int    `json:"resize_width,omitempty"` // Dynamic resize width (per-camera)
	ResizeHeight int   `json:"resize_height,omitempty"` // Dynamic resize height (per-camera)
}

type Config struct {
	NatsURL      string
	ResizeWidth  int
	ResizeHeight int
	TargetFPS    float64
	MetricsPort  string
	MotionThresh float64
	BufferSize   int
	Cameras      []CameraConfig
}

func Load() *Config {
	cfg := &Config{
		NatsURL:      getEnv("NATS_URL", "nats://localhost:4222"),
		ResizeWidth:  getEnvInt("RESIZE_WIDTH", 640),
		ResizeHeight: getEnvInt("RESIZE_HEIGHT", 360),
		TargetFPS:    getEnvFloat("TARGET_FPS", 5.0),
		MetricsPort:  getEnv("METRICS_PORT", "8080"),
		MotionThresh: 0.02,
		BufferSize:   10,
	}

	// Load Cameras from Database
	if err := cfg.loadCamerasFromDB(); err != nil {
		log.Printf("⚠️  Failed to load cameras from DB: %v", err)
		log.Println("⚠️  Falling back to legacy/empty config")
		cfg.Cameras = []CameraConfig{} 
	}

	return cfg
}

func (cfg *Config) loadCamerasFromDB() error {
	dbHost := getEnv("DB_HOST", "localhost")
	dbPort := getEnv("DB_PORT", "5432")
	dbUser := getEnv("DB_USER", "user")
	dbPass := getEnv("DB_PASSWORD", "password")
	dbName := getEnv("DB_NAME", "vigias")

	connStr := fmt.Sprintf("postgres://%s:%s@%s:%s/%s", dbUser, dbPass, dbHost, dbPort, dbName)
	log.Printf("Connecting to DB for config: postgres://%s:***@%s:%s/%s", dbUser, dbHost, dbPort, dbName)

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second) // Increased timeout for retries
	defer cancel()

	var conn *pgx.Conn
	var err error

	// Retry logic for DB connection
	maxRetries := 5
	for i := 0; i < maxRetries; i++ {
		conn, err = pgx.Connect(ctx, connStr)
		if err == nil {
			break
		}
		log.Printf("⚠️  DB Connection failed (attempt %d/%d): %v. Retrying in 2s...", i+1, maxRetries, err)
		time.Sleep(2 * time.Second)
	}

	if err != nil {
		return fmt.Errorf("failed to connect to DB after retries: %w", err)
	}
	defer conn.Close(context.Background())

	// Query Active Cameras with Org and Zone slugs
	query := `
		SELECT 
			c.id, c.name, c.rtsp_url, c.meta_info,
			o.slug as org_slug, o.id as org_id,
			z.slug as zone_slug, z.id as zone_id
		FROM cameras c
		JOIN org_zones z ON c.zone_id = z.id
		JOIN organizations o ON z.organization_id = o.id
		WHERE c.is_active = true
	`

	rows, err := conn.Query(ctx, query)
	if err != nil {
		return err
	}
	defer rows.Close()

	// Use slice of pointers to avoid reallocation issues invalidating map references
	var tempCameras []*CameraConfig
	cameraMap := make(map[string]*CameraConfig)

	for rows.Next() {
		var id, name, url, orgSlug, orgID, zoneSlug, zoneID string
		var metaInfo []byte

		if err := rows.Scan(&id, &name, &url, &metaInfo, &orgSlug, &orgID, &zoneSlug, &zoneID); err != nil {
			log.Printf("Error scanning camera row: %v", err)
			continue
		}

		// Handle Env Var substitution in URL immediately
		finalURL := replacePlaceholders(url)

		// Parse MetaInfo (for services list and priority)
		var meta map[string]interface{}
		if len(metaInfo) > 0 {
			json.Unmarshal(metaInfo, &meta)
		}

		services := []string{"security"} // Default
		if val, ok := meta["services"].([]interface{}); ok {
			services = make([]string, len(val))
			for i, v := range val {
				services[i] = fmt.Sprint(v)
			}
		}

		// Extract priority from meta_info (default to NORMAL)
		priority := "NORMAL"
		if val, ok := meta["priority"].(string); ok {
			priority = val
		}

		// Extract resize config from meta_info (per-camera override)
		resizeWidth := cfg.ResizeWidth   // Default from global config
		resizeHeight := cfg.ResizeHeight // Default from global config
		if resizeCfg, ok := meta["resize_config"].(map[string]interface{}); ok {
			if w, ok := resizeCfg["width"].(float64); ok {
				resizeWidth = int(w)
			}
			if h, ok := resizeCfg["height"].(float64); ok {
				resizeHeight = int(h)
			}
		}

		// Create on heap
		cam := &CameraConfig{
			ID:           id,
			Name:         name,
			URL:          finalURL,
			OrgSlug:      orgSlug,
			ZoneSlug:     zoneSlug,
			OrgID:        orgID,
			ZoneID:       zoneID,
			Services:     services,
			Features:     []string{},
			Zones:        make(map[string]interface{}),
			Priority:     priority,
			ResizeWidth:  resizeWidth,
			ResizeHeight: resizeHeight,
		}

		tempCameras = append(tempCameras, cam)
		cameraMap[id] = cam
	}

	// Close the first result set before querying AI configs
	rows.Close()

	// Now load all AI configs in a separate query (avoids "conn busy" error)
	// This will modify the structs pointed to by cameraMap (and thus tempCameras)
	// This will modify the structs pointed to by cameraMap (and thus tempCameras)
	if err := loadAllCameraAIConfigs(ctx, conn, cameraMap, cfg.ResizeWidth, cfg.ResizeHeight); err != nil {
		log.Printf("⚠️  Error loading AI configs: %v", err)
	}

	// Flatten pointers back to values for main Config struct
	cfg.Cameras = make([]CameraConfig, len(tempCameras))
	for i, c := range tempCameras {
		cfg.Cameras[i] = *c
	}
	
	log.Printf("✅ Loaded %d active cameras from Database", len(cfg.Cameras))
    for _, c := range cfg.Cameras {
        log.Printf("   -> Camera [%s]: Features=%v, Zones keys=%v", c.Name, c.Features, c.Zones)
    }
	return nil
}

// loadAllCameraAIConfigs loads AI configs for all cameras in a single query (avoids conn busy)
func loadAllCameraAIConfigs(ctx context.Context, conn *pgx.Conn, cameraMap map[string]*CameraConfig, width, height int) error {
	rows, err := conn.Query(ctx, `
		SELECT camera_id, event_type, roi_polygon, default_severity, confidence_threshold, debounce_seconds
		FROM camera_ai_configs
		WHERE is_active = true
		ORDER BY camera_id, event_type
	`)
	if err != nil {
		return err
	}
	defer rows.Close()

	configCount := 0
	for rows.Next() {
		var cameraID, eventType, severity string
		var roiPolygon []byte
		var conf float64
		var debounce int

		if err := rows.Scan(&cameraID, &eventType, &roiPolygon, &severity, &conf, &debounce); err != nil {
			log.Printf("Error scanning AI config row: %v", err)
			continue
		}

		cam, exists := cameraMap[cameraID]
		if !exists {
			continue // Camera not in our active list
		}

		configCount++

		// Add to Features list
		cam.Features = append(cam.Features, eventType)

		// Parse ROI
		var roi [][]float64
		if len(roiPolygon) > 0 {
			json.Unmarshal(roiPolygon, &roi)
		}

		// Determine trigger based on event type
		trigger := "enter"
		if eventType == "line_crossing" {
			trigger = "in_out"
		}

		// Scale normalized points (0-1) back to pixels (configured width/height)
		var scaledPoints [][]int
		if len(roi) > 0 {
			scaledPoints = make([][]int, len(roi))
			for i, p := range roi {
				if len(p) >= 2 {
					var x, y int
					
					// HEURISTIC: If coordinates are small floats (<= 1.5), treat as normalized 0-1
					if p[0] <= 1.5 && p[1] <= 1.5 {
						x = int(p[0] * float64(cam.ResizeWidth))
						y = int(p[1] * float64(cam.ResizeHeight))
					} else {
						// Absolute coordinates (assume they match the resolution or handled by inference scaling)
						x = int(p[0])
						y = int(p[1])
					}
					scaledPoints[i] = []int{x, y}
				}
			}
		}

		zoneConf := map[string]interface{}{
			"points":     scaledPoints,
			"trigger":    trigger,
			"confidence": conf,
			"debounce":   debounce,
		}

		cam.Zones[eventType] = zoneConf
	}

	log.Printf("✅ Loaded %d AI configs for cameras", configCount)
	return nil
}

// replacePlaceholders maps custom placeholders like {USER} to env vars
func replacePlaceholders(url string) string {
	// substitutions map: Placeholder -> Env Var Name
	subs := map[string]string{
		"{USER}":      "HIK_USER",
		"{PASS}":      "HIK_PASS",
		"{IP}":        "HIK_IP",
		"{PORT_RTSP}": "PORT_RTSP",
		"{PORT_HTTP}": "PORT_HTTP",
	}

	for ph, envKey := range subs {
		if val, ok := os.LookupEnv(envKey); ok {
			url = strings.ReplaceAll(url, ph, val)
		}
	}
	
	// Also attempt standard expansion for any remaining $VAR
	url = os.ExpandEnv(url)
	
	return url
}

func getEnv(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok {
		return value
	}
	return fallback
}

func getEnvInt(key string, fallback int) int {
	str := getEnv(key, "")
	if val, err := strconv.Atoi(str); err == nil {
		return val
	}
	return fallback
}

func getEnvFloat(key string, fallback float64) float64 {
	str := getEnv(key, "")
	if val, err := strconv.ParseFloat(str, 64); err == nil {
		return val
	}
	return fallback
}