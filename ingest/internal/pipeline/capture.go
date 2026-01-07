package pipeline

import (
	"context"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strings"
	"sync/atomic"
	"time"

	"vigias-ia/ingest/internal/config"

	"gocv.io/x/gocv"
)

var FramesCaptured uint64
var FramesDropped uint64

func CaptureWorker(cam config.CameraConfig, cfg *config.Config, out chan<- Frame) {
	defer close(out)

	// Initialize Stream Manager
	ctx := context.Background()
	streamMgr := NewStreamManager(ctx, cam)

	// Load camera settings from database
	if err := streamMgr.LoadCameraSettings(); err != nil {
		log.Printf("[%s] Warning: Using default reconnection settings", cam.Name)
	}

	// Configure RTSP Transport (tcp or udp)
	transport := os.Getenv("RTSP_TRANSPORT")
	if transport == "" {
		transport = "tcp" // Default to TCP if not set
	}
	os.Setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;"+transport)

	frameCount := 0
	var localFramesCaptured int64
	var localFramesDropped int64
	var connectionStartTime time.Time

	// Calculate interval based on FPS
	frameInterval := time.Second / time.Duration(cfg.TargetFPS)
	var lastFrameTime time.Time
	var lastHealthReport time.Time

	for {
		// Check if we should reconnect
		if !streamMgr.ShouldReconnect() {
			log.Printf("[%s] Stopping reconnection attempts", cam.Name)
			return
		}

		// Apply exponential backoff delay
		if streamMgr.connectionAttempts > 0 {
			delay := streamMgr.GetReconnectDelay()
			time.Sleep(delay)
		}

		log.Printf("[%s] Connecting to video source: %s", cam.ID, cam.URL)
		connectionStartTime = time.Now()

		finalURL := resolveURL(cam.URL)
		// Check for YouTube URL
		if strings.Contains(cam.URL, "youtube.com") || strings.Contains(cam.URL, "youtu.be") {
			log.Printf("[%s] Detected YouTube URL. Resolving stream...", cam.ID)
			cmd := exec.Command("yt-dlp", "-g", cam.URL)
			out, err := cmd.Output()
			if err != nil {
				streamMgr.OnConnectionFailure(err)
				continue
			}
			finalURL = strings.TrimSpace(string(out))
			log.Printf("[%s] Resolved YouTube URL: %s...", cam.ID, finalURL[:50]) // Log partial URL
		}

		webcam, err := gocv.VideoCaptureFile(finalURL)
		if err != nil {
			streamMgr.OnConnectionFailure(err)
			continue
		}

		if !webcam.IsOpened() {
			webcam.Close()
			streamMgr.OnConnectionFailure(fmt.Errorf("video source not opened"))
			continue
		}

		// Connection successful!
		streamMgr.OnConnectionSuccess()
		log.Printf("[%s] Video source connected. Took %v", cam.Name, time.Since(connectionStartTime))

		// Reset local counters for this connection session
		localFramesCaptured = 0
		localFramesDropped = 0
		lastHealthReport = time.Now()

		for {
			// Read continuously to drain RTSP buffer
			img := gocv.NewMat()
			if ok := webcam.Read(&img); !ok {
				log.Printf("[%s] Stream disconnected or EOF. Attempting reconnect...", cam.ID)
				img.Close()
				streamMgr.UpdateStatus(StatusOffline)
				break
			}
			if img.Empty() {
				img.Close()
				continue
			}

			// Check if it's time to process this frame
			now := time.Now()
			if now.Sub(lastFrameTime) < frameInterval {
				// Too fast, drop it to match TargetFPS
				img.Close()
				localFramesDropped++
				continue
			}

			lastFrameTime = now

			frameCount++
			localFramesCaptured++
			atomic.AddUint64(&FramesCaptured, 1)

			// Non-blocking send with drop logic
			select {
			case out <- Frame{ID: frameCount, Mat: img, Timestamp: now}:
				// Update last_seen timestamp every 5 seconds
				if now.Sub(lastHealthReport) >= 5*time.Second {
					streamMgr.UpdateLastSeen()

					// Calculate FPS and latency
					duration := now.Sub(lastHealthReport).Seconds()
					currentFPS := float64(localFramesCaptured) / duration
					latencyMs := int(now.Sub(connectionStartTime).Milliseconds())

					// Report health metrics every 30 seconds
					if now.Sub(lastHealthReport) >= 30*time.Second {
						streamMgr.ReportHealthMetrics(
							currentFPS,
							localFramesCaptured,
							localFramesDropped,
							latencyMs,
						)
						lastHealthReport = now
					} else {
						lastHealthReport = now
					}
				}
			default:
				img.Close() // Important: Close if we drop it!
				atomic.AddUint64(&FramesDropped, 1)
				localFramesDropped++
			}
		}
		webcam.Close()
	}
}

func resolveURL(rawURL string) string {
	// Simple replacement for known keys
	replacements := map[string]string{
		"{USER}":      os.Getenv("RTSP_USER"),
		"{PASS}":      os.Getenv("RTSP_PASS"),
		"{IP}":        os.Getenv("RTSP_IP"),
		"{PORT_RTSP}": os.Getenv("RTSP_PORT"),
	}

	res := rawURL
	for k, v := range replacements {
		if v != "" {
			res = strings.ReplaceAll(res, k, v)
		}
	}
	// Fallback/Safety: Log if braces remain? Or just return.
	return res
}
