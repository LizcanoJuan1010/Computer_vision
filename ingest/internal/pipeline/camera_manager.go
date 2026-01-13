package pipeline

import (
	"context"
	"encoding/json"
	"log"
	"sync"

	"github.com/nats-io/nats.go"
	"vigias-ia/ingest/internal/config"
)

// CameraManager manages dynamic addition/removal of cameras
type CameraManager struct {
	cameras         map[string]*CameraInstance
	mu              sync.RWMutex
	nc              *nats.Conn
	cfg             *config.Config
	cancelFuncs     map[string]context.CancelFunc
	fpsBoostHandler *FPSBoostHandler
}

// CameraInstance represents a running camera with its workers
type CameraInstance struct {
	Config     config.CameraConfig
	CancelFunc context.CancelFunc
	IsRunning  bool
	Publisher  *RTSPPublisher
}

// NewCameraManager creates a new camera manager
func NewCameraManager(nc *nats.Conn, cfg *config.Config, boostHandler *FPSBoostHandler) *CameraManager {
	return &CameraManager{
		cameras:         make(map[string]*CameraInstance),
		nc:              nc,
		cfg:             cfg,
		cancelFuncs:     make(map[string]context.CancelFunc),
		fpsBoostHandler: boostHandler,
	}
}

// StartCamera starts a camera capture pipeline
func (cm *CameraManager) StartCamera(cam config.CameraConfig) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	// Check if already running
	if instance, exists := cm.cameras[cam.ID]; exists && instance.IsRunning {
		log.Printf("[CameraManager] Camera %s is already running", cam.Name)
		return nil
	}

	// Create cancellable context for this camera
	_, cancel := context.WithCancel(context.Background())

	// Create channels
	captureChan := make(chan Frame, cm.cfg.BufferSize)
	processChan := make(chan Message, cm.cfg.BufferSize)
	
	// Create and Start RTSP Publisher
	publisher := NewRTSPPublisher(cam.ID)
	// We handle errors but try not to block start if ffmpeg fails (optional, but good for robustness)
	if err := publisher.Start(); err != nil {
		log.Printf("[CameraManager] ⚠️ Failed to start RTSP Publisher for %s: %v", cam.Name, err)
	}

	// Start workers
	go func() {
		defer func() {
			close(captureChan)
			log.Printf("[CameraManager] Capture worker stopped for %s", cam.Name)
		}()
		// Pass fpsBoostHandler to CaptureWorker
		CaptureWorker(cam, cm.cfg, captureChan, cm.fpsBoostHandler)
	}()

	go func() {
		defer func() {
			close(processChan)
			log.Printf("[CameraManager] Process worker stopped for %s", cam.Name)
		}()
		// NOW PASSING PUBLISHER
		ProcessWorker(cam, cm.cfg, captureChan, processChan, publisher)
	}()

	go func() {
		defer log.Printf("[CameraManager] Publish worker stopped for %s", cam.Name)
		PublishWorker(cm.nc, processChan)
	}()

	// Store instance
	cm.cameras[cam.ID] = &CameraInstance{
		Config:     cam,
		CancelFunc: cancel,
		IsRunning:  true,
		Publisher:  publisher,
	}
	cm.cancelFuncs[cam.ID] = cancel

	log.Printf("[CameraManager] ✅ Started camera: %s (ID: %s)", cam.Name, cam.ID)
	return nil
}

// StopCamera stops a camera capture pipeline
func (cm *CameraManager) StopCamera(cameraID string) error {
	cm.mu.Lock()
	defer cm.mu.Unlock()

	instance, exists := cm.cameras[cameraID]
	if !exists {
		log.Printf("[CameraManager] Camera %s not found", cameraID)
		return nil
	}

	if !instance.IsRunning {
		log.Printf("[CameraManager] Camera %s is already stopped", instance.Config.Name)
		return nil
	}
	
	// Stop Publisher
	if instance.Publisher != nil {
		instance.Publisher.Stop()
	}

	// Cancel context to stop workers
	if cancel, ok := cm.cancelFuncs[cameraID]; ok {
		cancel()
		delete(cm.cancelFuncs, cameraID)
	}

	instance.IsRunning = false
	log.Printf("[CameraManager] ⏹️  Stopped camera: %s (ID: %s)", instance.Config.Name, cameraID)

	return nil
}

// ReloadCamera reloads a camera configuration
func (cm *CameraManager) ReloadCamera(cameraID string) error {
	// Load fresh config from database
	cfg := config.Load()

	var newCam *config.CameraConfig
	for _, c := range cfg.Cameras {
		if c.ID == cameraID {
			newCam = &c
			break
		}
	}

	if newCam == nil {
		log.Printf("[CameraManager] Camera %s not found in database", cameraID)
		return cm.StopCamera(cameraID)
	}

	// Stop and restart
	cm.StopCamera(cameraID)
	return cm.StartCamera(*newCam)
}

// GetCameraStatus returns the status of a camera
func (cm *CameraManager) GetCameraStatus(cameraID string) map[string]interface{} {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	instance, exists := cm.cameras[cameraID]
	if !exists {
		return map[string]interface{}{
			"status": "not_found",
		}
	}

	return map[string]interface{}{
		"camera_id":   instance.Config.ID,
		"camera_name": instance.Config.Name,
		"is_running":  instance.IsRunning,
		"status":      "running",
	}
}

// ListCameras returns all cameras
func (cm *CameraManager) ListCameras() []map[string]interface{} {
	cm.mu.RLock()
	defer cm.mu.RUnlock()

	result := make([]map[string]interface{}, 0, len(cm.cameras))
	for _, instance := range cm.cameras {
		result = append(result, map[string]interface{}{
			"camera_id":   instance.Config.ID,
			"camera_name": instance.Config.Name,
			"is_running":  instance.IsRunning,
		})
	}
	return result
}

// SubscribeToCommands subscribes to NATS commands for camera control
func (cm *CameraManager) SubscribeToCommands() error {
	// Subscribe to camera.start commands
	_, err := cm.nc.Subscribe("commands.camera.*.start", func(msg *nats.Msg) {
		// Extract camera ID from subject: commands.camera.{ID}.start
		var payload struct {
			CameraID string `json:"camera_id"`
		}

		if err := json.Unmarshal(msg.Data, &payload); err != nil {
			log.Printf("[CameraManager] Error parsing start command: %v", err)
			msg.Respond([]byte(`{"status":"error","message":"Invalid payload"}`))
			return
		}

		// Load camera from database
		cfg := config.Load()
		var cam *config.CameraConfig
		for _, c := range cfg.Cameras {
			if c.ID == payload.CameraID {
				cam = &c
				break
			}
		}

		if cam == nil {
			msg.Respond([]byte(`{"status":"error","message":"Camera not found in database"}`))
			return
		}

		if err := cm.StartCamera(*cam); err != nil {
			resp := map[string]string{"status": "error", "message": err.Error()}
			data, _ := json.Marshal(resp)
			msg.Respond(data)
			return
		}

		msg.Respond([]byte(`{"status":"success","message":"Camera started"}`))
	})

	if err != nil {
		return err
	}

	// Subscribe to camera.stop commands
	_, err = cm.nc.Subscribe("commands.camera.*.stop", func(msg *nats.Msg) {
		var payload struct {
			CameraID string `json:"camera_id"`
		}

		if err := json.Unmarshal(msg.Data, &payload); err != nil {
			log.Printf("[CameraManager] Error parsing stop command: %v", err)
			msg.Respond([]byte(`{"status":"error","message":"Invalid payload"}`))
			return
		}

		if err := cm.StopCamera(payload.CameraID); err != nil {
			resp := map[string]string{"status": "error", "message": err.Error()}
			data, _ := json.Marshal(resp)
			msg.Respond(data)
			return
		}

		msg.Respond([]byte(`{"status":"success","message":"Camera stopped"}`))
	})

	if err != nil {
		return err
	}

	// Subscribe to camera.reload commands
	_, err = cm.nc.Subscribe("commands.camera.*.reload", func(msg *nats.Msg) {
		var payload struct {
			CameraID string `json:"camera_id"`
		}

		if err := json.Unmarshal(msg.Data, &payload); err != nil {
			log.Printf("[CameraManager] Error parsing reload command: %v", err)
			msg.Respond([]byte(`{"status":"error","message":"Invalid payload"}`))
			return
		}

		if err := cm.ReloadCamera(payload.CameraID); err != nil {
			resp := map[string]string{"status": "error", "message": err.Error()}
			data, _ := json.Marshal(resp)
			msg.Respond(data)
			return
		}

		msg.Respond([]byte(`{"status":"success","message":"Camera reloaded"}`))
	})

	if err != nil {
		return err
	}

	// Subscribe to camera.status commands
	_, err = cm.nc.Subscribe("commands.camera.*.status", func(msg *nats.Msg) {
		var payload struct {
			CameraID string `json:"camera_id"`
		}

		if err := json.Unmarshal(msg.Data, &payload); err != nil {
			log.Printf("[CameraManager] Error parsing status command: %v", err)
			msg.Respond([]byte(`{"status":"error","message":"Invalid payload"}`))
			return
		}

		status := cm.GetCameraStatus(payload.CameraID)
		data, _ := json.Marshal(status)
		msg.Respond(data)
	})

	if err != nil {
		return err
	}

	log.Printf("[CameraManager] ✅ Subscribed to NATS commands")
	return nil
}
