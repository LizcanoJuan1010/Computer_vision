package pipeline

import (
	"context"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
)

// CameraPriority represents camera priority levels
type CameraPriority string

const (
	PriorityLow      CameraPriority = "LOW"
	PriorityNormal   CameraPriority = "NORMAL"
	PriorityHigh     CameraPriority = "HIGH"
	PriorityCritical CameraPriority = "CRITICAL"
)

// FPSState represents the current FPS operational state
type FPSState string

const (
	FPSStateNormal    FPSState = "normal"    // Normal operation
	FPSStateBoosted   FPSState = "boosted"   // Boosted during important events
	FPSStateEmergency FPSState = "emergency" // Emergency throttle (GPU >95%)
)

// FPSManager handles dynamic FPS adjustment based on events and GPU load
type FPSManager struct {
	cameraID   string
	priority   CameraPriority
	targetFPS  float64
	currentFPS float64
	state      FPSState
	dbConnStr  string
	ctx        context.Context
	mu         sync.RWMutex

	// Boost management
	boostEndTime time.Time
	boostTimer   *time.Timer
}

// NewFPSManager creates a new FPS manager
func NewFPSManager(ctx context.Context, cameraID string, priority CameraPriority, targetFPS float64, dbConnStr string) *FPSManager {
	return &FPSManager{
		cameraID:   cameraID,
		priority:   priority,
		targetFPS:  targetFPS,
		currentFPS: targetFPS,
		state:      FPSStateNormal,
		dbConnStr:  dbConnStr,
		ctx:        ctx,
	}
}

// LoadPriorityFromDB loads camera priority from database
func (fm *FPSManager) LoadPriorityFromDB() error {
	conn, err := pgx.Connect(fm.ctx, fm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	var priority string
	var targetFPS float64

	err = conn.QueryRow(fm.ctx, `
		SELECT priority, target_fps
		FROM cameras
		WHERE id = $1
	`, fm.cameraID).Scan(&priority, &targetFPS)

	if err != nil {
		return fmt.Errorf("failed to load priority: %w", err)
	}

	fm.mu.Lock()
	fm.priority = CameraPriority(priority)
	fm.targetFPS = targetFPS
	fm.currentFPS = targetFPS
	fm.mu.Unlock()

	log.Printf("[FPSManager] Camera %s: Priority=%s, TargetFPS=%.2f", fm.cameraID, priority, targetFPS)
	return nil
}

// BoostFPS increases FPS based on event type and camera priority
func (fm *FPSManager) BoostFPS(eventType string, duration time.Duration) {
	fm.mu.Lock()
	defer fm.mu.Unlock()

	// If already in emergency mode, don't boost
	if fm.state == FPSStateEmergency {
		log.Printf("[FPSManager] ⚠️  Camera %s: Cannot boost during emergency throttle", fm.cameraID)
		return
	}

	// Calculate boost factor based on priority
	var boostFactor float64
	var boostDuration time.Duration

	switch fm.priority {
	case PriorityCritical:
		boostFactor = 2.0        // 2x FPS
		boostDuration = 30 * time.Second
	case PriorityHigh:
		boostFactor = 1.5        // 1.5x FPS
		boostDuration = 20 * time.Second
	case PriorityNormal:
		boostFactor = 1.2        // 1.2x FPS
		boostDuration = 15 * time.Second
	case PriorityLow:
		boostFactor = 1.0        // No boost
		boostDuration = 0
	default:
		boostFactor = 1.2
		boostDuration = 15 * time.Second
	}

	// Use custom duration if provided
	if duration > 0 {
		boostDuration = duration
	}

	// No boost for LOW priority
	if boostFactor == 1.0 {
		log.Printf("[FPSManager] Camera %s: LOW priority - no boost applied", fm.cameraID)
		return
	}

	boostedFPS := fm.targetFPS * boostFactor
	oldFPS := fm.currentFPS
	fm.currentFPS = boostedFPS
	fm.state = FPSStateBoosted
	fm.boostEndTime = time.Now().Add(boostDuration)

	log.Printf("[FPSManager] 🚀 Camera %s: FPS BOOSTED %.1f → %.1f (Event: %s, Priority: %s, Duration: %v)",
		fm.cameraID, oldFPS, boostedFPS, eventType, fm.priority, boostDuration)

	// Update database
	go fm.updateDatabaseState()

	// Cancel previous timer if exists
	if fm.boostTimer != nil {
		fm.boostTimer.Stop()
	}

	// Set timer to restore normal FPS
	fm.boostTimer = time.AfterFunc(boostDuration, func() {
		fm.RestoreNormalFPS()
	})
}

// RestoreNormalFPS restores FPS to normal target
func (fm *FPSManager) RestoreNormalFPS() {
	fm.mu.Lock()
	defer fm.mu.Unlock()

	// Don't restore if in emergency mode
	if fm.state == FPSStateEmergency {
		return
	}

	oldFPS := fm.currentFPS
	fm.currentFPS = fm.targetFPS
	fm.state = FPSStateNormal

	log.Printf("[FPSManager] ✅ Camera %s: FPS restored to normal %.1f → %.1f",
		fm.cameraID, oldFPS, fm.currentFPS)

	// Update database
	go fm.updateDatabaseState()
}

// CheckGPUThrottle checks GPU utilization and applies emergency throttle if needed
func (fm *FPSManager) CheckGPUThrottle(gpuUtil float64) {
	fm.mu.Lock()
	defer fm.mu.Unlock()

	const emergencyThreshold = 95.0
	const restoreThreshold = 85.0
	const emergencyFPS = 10.0

	if gpuUtil >= emergencyThreshold && fm.state != FPSStateEmergency {
		// Enter emergency mode
		oldFPS := fm.currentFPS
		fm.currentFPS = emergencyFPS
		fm.state = FPSStateEmergency

		// Cancel boost timer if active
		if fm.boostTimer != nil {
			fm.boostTimer.Stop()
			fm.boostTimer = nil
		}

		log.Printf("[FPSManager] 🚨 Camera %s: EMERGENCY THROTTLE %.1f → %.1f FPS (GPU: %.1f%%)",
			fm.cameraID, oldFPS, emergencyFPS, gpuUtil)

		go fm.updateDatabaseState()

	} else if gpuUtil < restoreThreshold && fm.state == FPSStateEmergency {
		// Exit emergency mode
		oldFPS := fm.currentFPS
		fm.currentFPS = fm.targetFPS
		fm.state = FPSStateNormal

		log.Printf("[FPSManager] ✅ Camera %s: Emergency throttle released %.1f → %.1f FPS (GPU: %.1f%%)",
			fm.cameraID, oldFPS, fm.currentFPS, gpuUtil)

		go fm.updateDatabaseState()
	}
}

// updateDatabaseState updates FPS state in database
func (fm *FPSManager) updateDatabaseState() error {
	conn, err := pgx.Connect(fm.ctx, fm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	fm.mu.RLock()
	currentFPS := fm.currentFPS
	state := fm.state
	fm.mu.RUnlock()

	_, err = conn.Exec(fm.ctx, `
		UPDATE cameras
		SET current_fps = $1,
		    fps_degraded = $2,
		    updated_at = NOW()
		WHERE id = $3
	`, currentFPS, state == FPSStateEmergency, fm.cameraID)

	if err != nil {
		return fmt.Errorf("failed to update FPS state: %w", err)
	}

	return nil
}

// GetCurrentFPS returns the current adjusted FPS
func (fm *FPSManager) GetCurrentFPS() float64 {
	fm.mu.RLock()
	defer fm.mu.RUnlock()
	return fm.currentFPS
}

// GetTargetFPS returns the target FPS
func (fm *FPSManager) GetTargetFPS() float64 {
	fm.mu.RLock()
	defer fm.mu.RUnlock()
	return fm.targetFPS
}

// GetState returns the current FPS state
func (fm *FPSManager) GetState() FPSState {
	fm.mu.RLock()
	defer fm.mu.RUnlock()
	return fm.state
}

// GetPriority returns the camera priority
func (fm *FPSManager) GetPriority() CameraPriority {
	fm.mu.RLock()
	defer fm.mu.RUnlock()
	return fm.priority
}

// GetFrameInterval returns the time duration between frames based on current FPS
func (fm *FPSManager) GetFrameInterval() time.Duration {
	fm.mu.RLock()
	defer fm.mu.RUnlock()
	return time.Second / time.Duration(fm.currentFPS)
}

// MonitorGPU continuously monitors GPU and applies emergency throttle if needed
func (fm *FPSManager) MonitorGPU(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	resourceMonitor := NewResourceMonitor(fm.ctx, fm.cameraID, fm.dbConnStr)

	for {
		select {
		case <-fm.ctx.Done():
			return
		case <-ticker.C:
			// Get GPU utilization
			gpuUtil := resourceMonitor.GetGPUPercent()

			// Check and apply throttle if needed
			fm.CheckGPUThrottle(gpuUtil)
		}
	}
}