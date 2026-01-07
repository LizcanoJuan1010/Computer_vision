package pipeline

import (
	"context"
	"fmt"
	"log"
	"runtime"
	"time"

	"github.com/jackc/pgx/v5"
)

// ResourceMonitor tracks system resource usage
type ResourceMonitor struct {
	cameraID  string
	dbConnStr string
	ctx       context.Context
}

// NewResourceMonitor creates a new resource monitor
func NewResourceMonitor(ctx context.Context, cameraID, dbConnStr string) *ResourceMonitor {
	return &ResourceMonitor{
		cameraID:  cameraID,
		dbConnStr: dbConnStr,
		ctx:       ctx,
	}
}

// GetCPUPercent returns estimated CPU usage percentage
// Note: This is a simplified estimation based on goroutine count
func (rm *ResourceMonitor) GetCPUPercent() float64 {
	// Simple heuristic: number of goroutines / CPU cores
	numGoroutines := float64(runtime.NumGoroutine())
	numCPU := float64(runtime.NumCPU())

	// Rough estimation: assume each goroutine uses ~5% of a core
	cpuPercent := (numGoroutines / numCPU) * 5.0

	// Cap at 100%
	if cpuPercent > 100.0 {
		cpuPercent = 100.0
	}

	return cpuPercent
}

// GetMemoryMB returns memory usage in megabytes
func (rm *ResourceMonitor) GetMemoryMB() int {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	// Alloc is bytes of allocated heap objects
	return int(m.Alloc / 1024 / 1024)
}

// GetGPUPercent returns GPU usage percentage
// Note: This is a placeholder. Real GPU monitoring requires external libraries
func (rm *ResourceMonitor) GetGPUPercent() float64 {
	// TODO: Implement real GPU monitoring using:
	// - NVIDIA Management Library (NVML) for NVIDIA GPUs
	// - ROCm SMI for AMD GPUs
	// For now, return 0.0 as placeholder
	return 0.0
}

// ReportMetrics reports resource metrics to database
func (rm *ResourceMonitor) ReportMetrics(fps float64, framesCaptured, framesDropped int64, latencyMs int, status CameraStatus) error {
	conn, err := pgx.Connect(rm.ctx, rm.dbConnStr)
	if err != nil {
		return fmt.Errorf("failed to connect to DB: %w", err)
	}
	defer conn.Close(context.Background())

	// Get resource metrics
	cpuPercent := rm.GetCPUPercent()
	gpuPercent := rm.GetGPUPercent()
	memoryMB := rm.GetMemoryMB()

	_, err = conn.Exec(rm.ctx, `
		INSERT INTO camera_health_metrics (
			camera_id, fps, frames_captured, frames_dropped,
			latency_ms, cpu_percent, gpu_percent, memory_mb, status
		) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
	`, rm.cameraID, fps, framesCaptured, framesDropped, latencyMs,
	   cpuPercent, gpuPercent, memoryMB, string(status))

	if err != nil {
		return fmt.Errorf("failed to insert health metrics: %w", err)
	}

	log.Printf("[ResourceMonitor] Camera %s - FPS: %.2f, CPU: %.1f%%, Mem: %dMB, Latency: %dms",
		rm.cameraID, fps, cpuPercent, memoryMB, latencyMs)

	return nil
}

// StartPeriodicReporting starts periodic resource reporting
func (rm *ResourceMonitor) StartPeriodicReporting(interval time.Duration, statusFn func() CameraStatus) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-rm.ctx.Done():
			return
		case <-ticker.C:
			cpuPercent := rm.GetCPUPercent()
			memoryMB := rm.GetMemoryMB()
			gpuPercent := rm.GetGPUPercent()

			log.Printf("[ResourceMonitor] %s - CPU: %.1f%%, Mem: %dMB, GPU: %.1f%%",
				rm.cameraID, cpuPercent, memoryMB, gpuPercent)
		}
	}
}
