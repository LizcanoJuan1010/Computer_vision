package pipeline

import (
	"context"
	"fmt"
	"log"
	"math"
	"os"
	"time"

	"github.com/jackc/pgx/v5"
	"vigias-ia/ingest/internal/config"
)

// CameraStatus represents the current state of a camera connection
type CameraStatus string

const (
	StatusOnline      CameraStatus = "ONLINE"
	StatusOffline     CameraStatus = "OFFLINE"
	StatusError       CameraStatus = "ERROR"
	StatusMaintenance CameraStatus = "MAINTENANCE"
)

// StreamManager handles connection lifecycle, reconnection logic, and status tracking
type StreamManager struct {
	cameraID                 string
	cameraName               string
	status                   CameraStatus
	connectionAttempts       int
	maxReconnectAttempts     int
	baseReconnectInterval    time.Duration
	lastError                string
	lastErrorAt              time.Time
	dbConnStr                string
	ctx                      context.Context
}

// NewStreamManager creates a new stream manager for a camera
func NewStreamManager(ctx context.Context, cam config.CameraConfig) *StreamManager {
	// Build DB connection string
	dbHost := getEnvOrDefault("DB_HOST", "localhost")
	dbPort := getEnvOrDefault("DB_PORT", "5432")
	dbUser := getEnvOrDefault("DB_USER", "user")
	dbPass := getEnvOrDefault("DB_PASSWORD", "password")
	dbName := getEnvOrDefault("DB_NAME", "vigias")

	connStr := fmt.Sprintf("postgres://%s:%s@%s:%s/%s", dbUser, dbPass, dbHost, dbPort, dbName)

	return &StreamManager{
		cameraID:                 cam.ID,
		cameraName:               cam.Name,
		status:                   StatusOffline,
		connectionAttempts:       0,
		maxReconnectAttempts:     12, // Will be loaded from DB
		baseReconnectInterval:    5 * time.Second,
		dbConnStr:                connStr,
		ctx:                      ctx,
	}
}

// LoadCameraSettings loads max_reconnect_attempts and reconnect_interval from database
func (sm *StreamManager) LoadCameraSettings() error {
	conn, err := pgx.Connect(sm.ctx, sm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	var maxAttempts int
	var intervalSeconds int

	err = conn.QueryRow(sm.ctx, `
		SELECT max_reconnect_attempts, reconnect_interval_seconds
		FROM cameras
		WHERE id = $1
	`, sm.cameraID).Scan(&maxAttempts, &intervalSeconds)

	if err != nil {
		log.Printf("[%s] Warning: Could not load camera settings from DB: %v. Using defaults.", sm.cameraName, err)
		return err
	}

	sm.maxReconnectAttempts = maxAttempts
	sm.baseReconnectInterval = time.Duration(intervalSeconds) * time.Second

	log.Printf("[%s] Loaded settings: max_attempts=%d, base_interval=%v", sm.cameraName, maxAttempts, sm.baseReconnectInterval)
	return nil
}

// UpdateStatus updates the camera status in the database
func (sm *StreamManager) UpdateStatus(newStatus CameraStatus) error {
	sm.status = newStatus

	conn, err := pgx.Connect(sm.ctx, sm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	_, err = conn.Exec(sm.ctx, `
		UPDATE cameras
		SET status = $1, last_seen_at = NOW()
		WHERE id = $2
	`, string(newStatus), sm.cameraID)

	if err != nil {
		return fmt.Errorf("failed to update status: %w", err)
	}

	log.Printf("[%s] Status updated to: %s", sm.cameraName, newStatus)
	return nil
}

// RecordError records an error in the database
func (sm *StreamManager) RecordError(errorMsg string) error {
	sm.lastError = errorMsg
	sm.lastErrorAt = time.Now()

	conn, err := pgx.Connect(sm.ctx, sm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	_, err = conn.Exec(sm.ctx, `
		UPDATE cameras
		SET last_error = $1, last_error_at = NOW(), connection_attempts = connection_attempts + 1
		WHERE id = $2
	`, errorMsg, sm.cameraID)

	if err != nil {
		return fmt.Errorf("failed to record error: %w", err)
	}

	return nil
}

// LogReconnectionAttempt logs a reconnection attempt to the database
func (sm *StreamManager) LogReconnectionAttempt(attemptNum int, success bool, errorMsg string) error {
	conn, err := pgx.Connect(sm.ctx, sm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	var reconnectedAt *time.Time
	if success {
		now := time.Now()
		reconnectedAt = &now
	}

	_, err = conn.Exec(sm.ctx, `
		INSERT INTO camera_reconnection_log (camera_id, attempt_number, success, error_message, reconnected_at)
		VALUES ($1, $2, $3, $4, $5)
	`, sm.cameraID, attemptNum, success, errorMsg, reconnectedAt)

	if err != nil {
		return fmt.Errorf("failed to log reconnection attempt: %w", err)
	}

	return nil
}

// OnConnectionSuccess handles successful connection
func (sm *StreamManager) OnConnectionSuccess() {
	sm.connectionAttempts = 0
	sm.UpdateStatus(StatusOnline)
	sm.LogReconnectionAttempt(sm.connectionAttempts, true, "")
	log.Printf("[%s] ✅ Connection successful", sm.cameraName)
}

// OnConnectionFailure handles connection failure
func (sm *StreamManager) OnConnectionFailure(err error) {
	sm.connectionAttempts++
	errorMsg := err.Error()

	sm.RecordError(errorMsg)
	sm.UpdateStatus(StatusError)
	sm.LogReconnectionAttempt(sm.connectionAttempts, false, errorMsg)

	log.Printf("[%s] ❌ Connection failed (attempt %d/%d): %v",
		sm.cameraName, sm.connectionAttempts, sm.maxReconnectAttempts, err)
}

// ShouldReconnect checks if we should attempt another reconnection
func (sm *StreamManager) ShouldReconnect() bool {
	if sm.status == StatusMaintenance {
		log.Printf("[%s] Camera in MAINTENANCE mode. Skipping reconnection.", sm.cameraName)
		return false
	}

	if sm.connectionAttempts >= sm.maxReconnectAttempts {
		log.Printf("[%s] ⚠️  Max reconnection attempts (%d) reached. Giving up.", sm.cameraName, sm.maxReconnectAttempts)
		sm.UpdateStatus(StatusOffline)
		return false
	}

	return true
}

// GetReconnectDelay calculates the delay before next reconnection attempt using exponential backoff
func (sm *StreamManager) GetReconnectDelay() time.Duration {
	// Exponential backoff with jitter: delay = base * 2^(attempts - 1)
	// Capped at 5 minutes
	maxDelay := 5 * time.Minute

	if sm.connectionAttempts == 0 {
		return sm.baseReconnectInterval
	}

	// Exponential backoff
	exponent := float64(sm.connectionAttempts - 1)
	delay := time.Duration(float64(sm.baseReconnectInterval) * math.Pow(2, exponent))

	if delay > maxDelay {
		delay = maxDelay
	}

	log.Printf("[%s] Next reconnection in %v (attempt %d)", sm.cameraName, delay, sm.connectionAttempts+1)
	return delay
}

// ReportHealthMetrics reports current health metrics to database with resource monitoring
func (sm *StreamManager) ReportHealthMetrics(fps float64, framesCaptured, framesDropped int64, latencyMs int) error {
	// Create resource monitor
	resourceMonitor := NewResourceMonitor(sm.ctx, sm.cameraID, sm.dbConnStr)

	// Report metrics with resource usage
	return resourceMonitor.ReportMetrics(fps, framesCaptured, framesDropped, latencyMs, sm.status)
}

// UpdateLastSeen updates the last_seen_at timestamp
func (sm *StreamManager) UpdateLastSeen() error {
	conn, err := pgx.Connect(sm.ctx, sm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	_, err = conn.Exec(sm.ctx, `
		UPDATE cameras
		SET last_seen_at = NOW(), last_frame_at = NOW()
		WHERE id = $1
	`, sm.cameraID)

	return err
}

// Helper function
func getEnvOrDefault(key, fallback string) string {
	if value, ok := os.LookupEnv(key); ok {
		return value
	}
	return fallback
}
