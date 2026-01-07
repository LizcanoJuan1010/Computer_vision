package pipeline

import (
	"context"
	"fmt"
	"log"
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

// FPSManager handles dynamic FPS adjustment based on priority and resources
type FPSManager struct {
	cameraID   string
	priority   CameraPriority
	targetFPS  float64
	currentFPS float64
	degraded   bool
	dbConnStr  string
	ctx        context.Context
}

// NewFPSManager creates a new FPS manager
func NewFPSManager(ctx context.Context, cameraID string, priority CameraPriority, targetFPS float64, dbConnStr string) *FPSManager {
	return &FPSManager{
		cameraID:   cameraID,
		priority:   priority,
		targetFPS:  targetFPS,
		currentFPS: targetFPS,
		degraded:   false,
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

	fm.priority = CameraPriority(priority)
	fm.targetFPS = targetFPS
	fm.currentFPS = targetFPS

	log.Printf("[FPSManager] Camera %s: Priority=%s, TargetFPS=%.2f", fm.cameraID, priority, targetFPS)
	return nil
}

// AdjustFPS adjusts FPS based on system load and priority
func (fm *FPSManager) AdjustFPS(systemLoad float64, totalCameras int) float64 {
	// High system load threshold: 80%
	highLoadThreshold := 80.0

	// If system is not under pressure, return target FPS
	if systemLoad < highLoadThreshold {
		if fm.degraded {
			fm.RestoreFPS()
		}
		return fm.targetFPS
	}

	// System is under pressure - adjust based on priority
	var adjustedFPS float64

	switch fm.priority {
	case PriorityCritical:
		// Critical cameras: maintain 90% of target FPS
		adjustedFPS = fm.targetFPS * 0.9

	case PriorityHigh:
		// High priority: maintain 70% of target FPS
		adjustedFPS = fm.targetFPS * 0.7

	case PriorityNormal:
		// Normal priority: maintain 50% of target FPS
		adjustedFPS = fm.targetFPS * 0.5

	case PriorityLow:
		// Low priority: drop to 30% of target FPS
		adjustedFPS = fm.targetFPS * 0.3

	default:
		adjustedFPS = fm.targetFPS * 0.5
	}

	// Ensure minimum FPS of 5
	if adjustedFPS < 5.0 {
		adjustedFPS = 5.0
	}

	// Update if changed
	if adjustedFPS != fm.currentFPS {
		fm.DegradeFPS(adjustedFPS)
	}

	return adjustedFPS
}

// DegradeFPS marks FPS as degraded and updates database
func (fm *FPSManager) DegradeFPS(newFPS float64) error {
	oldFPS := fm.currentFPS
	fm.currentFPS = newFPS
	fm.degraded = true

	log.Printf("[FPSManager] ⚠️  Camera %s: FPS degraded %.2f → %.2f (Priority: %s)",
		fm.cameraID, oldFPS, newFPS, fm.priority)

	// Update database
	return fm.updateDatabaseFPS()
}

// RestoreFPS restores FPS to target and updates database
func (fm *FPSManager) RestoreFPS() error {
	oldFPS := fm.currentFPS
	fm.currentFPS = fm.targetFPS
	fm.degraded = false

	log.Printf("[FPSManager] ✅ Camera %s: FPS restored %.2f → %.2f",
		fm.cameraID, oldFPS, fm.currentFPS)

	// Update database
	return fm.updateDatabaseFPS()
}

// updateDatabaseFPS updates current_fps and fps_degraded in database
func (fm *FPSManager) updateDatabaseFPS() error {
	conn, err := pgx.Connect(fm.ctx, fm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	_, err = conn.Exec(fm.ctx, `
		UPDATE cameras
		SET current_fps = $1, fps_degraded = $2
		WHERE id = $3
	`, fm.currentFPS, fm.degraded, fm.cameraID)

	if err != nil {
		return fmt.Errorf("failed to update FPS: %w", err)
	}

	return nil
}

// GetCurrentFPS returns the current adjusted FPS
func (fm *FPSManager) GetCurrentFPS() float64 {
	return fm.currentFPS
}

// GetTargetFPS returns the target FPS
func (fm *FPSManager) GetTargetFPS() float64 {
	return fm.targetFPS
}

// IsDegraded returns whether FPS is currently degraded
func (fm *FPSManager) IsDegraded() bool {
	return fm.degraded
}

// GetFrameInterval returns the time duration between frames based on current FPS
func (fm *FPSManager) GetFrameInterval() time.Duration {
	return time.Second / time.Duration(fm.currentFPS)
}

// MonitorAndAdjust continuously monitors system and adjusts FPS
func (fm *FPSManager) MonitorAndAdjust(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	resourceMonitor := NewResourceMonitor(fm.ctx, fm.cameraID, fm.dbConnStr)

	for {
		select {
		case <-fm.ctx.Done():
			return
		case <-ticker.C:
			// Get current CPU usage as system load indicator
			cpuLoad := resourceMonitor.GetCPUPercent()

			// Adjust FPS based on load
			// Note: totalCameras would need to be passed or tracked globally
			adjustedFPS := fm.AdjustFPS(cpuLoad, 1)

			if adjustedFPS != fm.currentFPS {
				log.Printf("[FPSManager] Adjusted FPS for camera %s: %.2f (Load: %.1f%%)",
					fm.cameraID, adjustedFPS, cpuLoad)
			}
		}
	}
}
