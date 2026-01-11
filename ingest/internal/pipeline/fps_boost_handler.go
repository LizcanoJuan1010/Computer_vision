package pipeline

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/nats-io/nats.go"
)

// Global FPS boost handler instance
var GlobalFPSBoostHandler *FPSBoostHandler

// FPSBoostEvent represents an FPS boost event from inference
type FPSBoostEvent struct {
	CameraID  string `json:"camera_id"`
	EventType string `json:"event_type"` // intrusion, face_recognition, line_crossing, etc
	Duration  int    `json:"duration"`   // Duration in seconds
}

// FPSBoostHandler manages FPS boost events via NATS
type FPSBoostHandler struct {
	nc            *nats.Conn
	ctx           context.Context
	fpsManagers   map[string]*FPSManager // cameraID -> FPSManager
	mu            sync.RWMutex
	subscription  *nats.Subscription
}

// NewFPSBoostHandler creates a new FPS boost handler
func NewFPSBoostHandler(ctx context.Context, nc *nats.Conn) *FPSBoostHandler {
	handler := &FPSBoostHandler{
		nc:          nc,
		ctx:         ctx,
		fpsManagers: make(map[string]*FPSManager),
	}
	GlobalFPSBoostHandler = handler // Set global instance for easy access if needed
	return handler
}

// RegisterFPSManager registers an FPS manager for a camera
func (h *FPSBoostHandler) RegisterFPSManager(cameraID string, fpsManager *FPSManager) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.fpsManagers[cameraID] = fpsManager
	log.Printf("[FPSBoostHandler] Registered FPSManager for camera %s", cameraID)
}

// Start subscribes to FPS boost events
func (h *FPSBoostHandler) Start() error {
	// Subscribe to all FPS boost events: events.fps.boost.*
	subject := "events.fps.boost.*"

	var err error
	h.subscription, err = h.nc.Subscribe(subject, func(msg *nats.Msg) {
		h.handleBoostEvent(msg)
	})

	if err != nil {
		return fmt.Errorf("failed to subscribe to %s: %w", subject, err)
	}

	log.Printf("[FPSBoostHandler] ✅ Subscribed to %s", subject)
	return nil
}

// handleBoostEvent processes incoming boost events
func (h *FPSBoostHandler) handleBoostEvent(msg *nats.Msg) {
	var event FPSBoostEvent

	if err := json.Unmarshal(msg.Data, &event); err != nil {
		log.Printf("[FPSBoostHandler] ❌ Failed to unmarshal boost event: %v", err)
		return
	}

	log.Printf("[FPSBoostHandler] 📨 Received boost event: Camera=%s, Event=%s, Duration=%ds",
		event.CameraID, event.EventType, event.Duration)

	// Get FPS manager for this camera
	h.mu.RLock()
	fpsManager, exists := h.fpsManagers[event.CameraID]
	h.mu.RUnlock()

	if !exists {
		log.Printf("[FPSBoostHandler] ⚠️  No FPSManager found for camera %s", event.CameraID)
		return
	}

	// Apply boost
	duration := time.Duration(event.Duration) * time.Second
	fpsManager.BoostFPS(event.EventType, duration)
}

// Stop unsubscribes from boost events
func (h *FPSBoostHandler) Stop() error {
	if h.subscription != nil {
		if err := h.subscription.Unsubscribe(); err != nil {
			return fmt.Errorf("failed to unsubscribe: %w", err)
		}
		log.Printf("[FPSBoostHandler] Unsubscribed from boost events")
	}
	return nil
}