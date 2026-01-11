package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync/atomic"
	"syscall"
	"time"

	"gocv.io/x/gocv"

	"github.com/nats-io/nats.go"

	"vigias-ia/ingest/internal/config"
	"vigias-ia/ingest/internal/pipeline"
)

func main() {
	// Load Config
	cfg := config.Load()

	// Setup graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start Metrics Server
	go startMetricsServer(cfg)

	// Connect to NATS with Retry Logic
	log.Printf("Connecting to NATS at %s...", cfg.NatsURL)
	var nc *nats.Conn
	var err error
	maxRetries := 10
	retryInterval := 2 * time.Second

	for i := 0; i < maxRetries; i++ {
		nc, err = nats.Connect(cfg.NatsURL)
		if err == nil && nc != nil {
			log.Printf("Connected to NATS successfully!")
			break
		}
		if i == maxRetries-1 {
			log.Fatalf("Error connecting to NATS after %d attempts: %v", maxRetries, err)
		}
		log.Printf("NATS connection failed (attempt %d/%d): %v. Retrying in %v...", i+1, maxRetries, err, retryInterval)
		time.Sleep(retryInterval)
	}
	defer nc.Close()

	// Create Camera Manager for hot-reload support
	// Create default FPS Boost Handler
	fpsBoostHandler := pipeline.NewFPSBoostHandler(context.Background(), nc)
	if err := fpsBoostHandler.Start(); err != nil {
		log.Printf("Failed to start FPS Boost Handler: %v", err)
	}

	// Create CameraManager with FPS Boost support
	cameraManager := pipeline.NewCameraManager(nc, cfg, fpsBoostHandler)

	// Subscribe to NATS commands for dynamic camera control
	if err := cameraManager.SubscribeToCommands(); err != nil {
		log.Fatalf("Failed to subscribe to camera commands: %v", err)
	}

	// Create and start Global FPS Boost Handler
	ctx := context.Background()
	pipeline.GlobalFPSBoostHandler = pipeline.NewFPSBoostHandler(ctx, nc)
	if err := pipeline.GlobalFPSBoostHandler.Start(); err != nil {
		log.Fatalf("Failed to start FPS boost handler: %v", err)
	}
	defer pipeline.GlobalFPSBoostHandler.Stop()

	log.Printf("Starting Ingestion Service for %d cameras...", len(cfg.Cameras))

	// Start all configured cameras using CameraManager
	for _, cam := range cfg.Cameras {
		if err := cameraManager.StartCamera(cam); err != nil {
			log.Printf("Failed to start camera %s: %v", cam.Name, err)
		}
	}

	log.Printf("✅ Camera Manager ready - Hot-reload enabled via NATS")

	// Wait for shutdown signal
	<-sigChan
	fmt.Println("\nShutting down...")
}

func startMetricsServer(cfg *config.Config) {
	http.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		captured := atomic.LoadUint64(&pipeline.FramesCaptured)
		sent := atomic.LoadUint64(&pipeline.FramesSent)
		dropped := atomic.LoadUint64(&pipeline.FramesDropped)

		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		
		fmt.Fprintf(w, "# HELP camera_frames_captured_total Total number of frames captured from video sources\n")
		fmt.Fprintf(w, "# TYPE camera_frames_captured_total counter\n")
		fmt.Fprintf(w, "camera_frames_captured_total %d\n", captured)

		fmt.Fprintf(w, "# HELP camera_frames_sent_total Total number of frames sent to NATS\n")
		fmt.Fprintf(w, "# TYPE camera_frames_sent_total counter\n")
		fmt.Fprintf(w, "camera_frames_sent_total %d\n", sent)

		fmt.Fprintf(w, "# HELP camera_frames_dropped_total Total number of frames dropped due to buffer overflow\n")
		fmt.Fprintf(w, "# TYPE camera_frames_dropped_total counter\n")
		fmt.Fprintf(w, "camera_frames_dropped_total %d\n", dropped)
	})

	// 1. Snapshot Handler
	http.HandleFunc("/snapshot/", func(w http.ResponseWriter, r *http.Request) {
		camID := r.URL.Path[len("/snapshot/"):]
		img, ok := pipeline.Hub.GetSnapshot(camID)
		if !ok {
			http.Error(w, "Camera not found or not ready", http.StatusNotFound)
			return
		}
		defer img.Close()

		buf, err := gocv.IMEncode(".jpg", img)
		if err != nil {
			http.Error(w, "Failed to encode image", http.StatusInternalServerError)
			return
		}
		defer buf.Close()

		w.Header().Set("Content-Type", "image/jpeg")
		w.Header().Set("Content-Length", fmt.Sprint(len(buf.GetBytes())))
		w.Write(buf.GetBytes())
	})

	// 2. MJPEG Stream Handler
	http.HandleFunc("/stream/", func(w http.ResponseWriter, r *http.Request) {
		camID := r.URL.Path[len("/stream/"):]
		
		// Set Multipart Header
		w.Header().Set("Content-Type", "multipart/x-mixed-replace; boundary=frame")
		w.WriteHeader(http.StatusOK)

		ticker := time.NewTicker(time.Millisecond * 66) // ~15 FPS
		defer ticker.Stop()

		for {
			select {
			case <-r.Context().Done():
				return
			case <-ticker.C:
				img, ok := pipeline.Hub.GetSnapshot(camID)
				if !ok {
					continue
				}
				
				buf, err := gocv.IMEncode(".jpg", img)
				img.Close() // Close immediately after encode
				
				if err != nil {
					continue
				}

				// Write Multipart Frame
				fmt.Fprintf(w, "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n", len(buf.GetBytes()))
				w.Write(buf.GetBytes())
				w.Write([]byte("\r\n"))
				buf.Close()
			}
		}
	})

	log.Printf("HTTP Server (Metrics/Stream/Snapshot) listening on :%s", cfg.MetricsPort)
	log.Fatal(http.ListenAndServe(":"+cfg.MetricsPort, nil))
}