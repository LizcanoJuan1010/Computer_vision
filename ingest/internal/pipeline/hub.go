package pipeline

import (
	"sync"
	"gocv.io/x/gocv"
)

// FrameHub is a thread-safe store for the latest frame of each camera.
// Used for MJPEG streaming and Snapshots.
type FrameHub struct {
	mu     sync.RWMutex
	frames map[string]gocv.Mat
}

var Hub = &FrameHub{
	frames: make(map[string]gocv.Mat),
}

// UpdateFrame updates the latest frame for a camera.
// It clones the frame because the original might be closed/reused.
func (h *FrameHub) UpdateFrame(cameraID string, img gocv.Mat) {
	h.mu.Lock()
	defer h.mu.Unlock()

	// Close old frame if exists to prevent memory leak
	if old, ok := h.frames[cameraID]; ok {
		old.Close()
	}

	h.frames[cameraID] = img.Clone()
}

// GetSnapshot returns a clone of the latest frame.
// Caller is responsible for Closing the returned Mat.
func (h *FrameHub) GetSnapshot(cameraID string) (gocv.Mat, bool) {
	h.mu.RLock()
	defer h.mu.RUnlock()

	if img, ok := h.frames[cameraID]; ok && !img.Empty() {
		return img.Clone(), true
	}
	return gocv.NewMat(), false
}
