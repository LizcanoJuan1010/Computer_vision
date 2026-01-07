package pipeline

import (
	"sync"

	"gocv.io/x/gocv"
)

// RingBuffer holds the last N frames
type RingBuffer struct {
	mu       sync.Mutex
	frames   []Frame
	head     int
	size     int
	capacity int
}

func NewRingBuffer(capacity int) *RingBuffer {
	return &RingBuffer{
		frames:   make([]Frame, capacity),
		capacity: capacity,
	}
}

// Add adds a frame to the buffer, overwriting the oldest if full
// Returns the overwritten Mat and true if one was dropped, otherwise empty Mat and false
func (rb *RingBuffer) Add(f Frame) (gocv.Mat, bool) {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	var droppedMat gocv.Mat
	dropped := false

	if rb.size == rb.capacity {
		droppedMat = rb.frames[rb.head].Mat
		dropped = true
	}

	rb.frames[rb.head] = f
	rb.head = (rb.head + 1) % rb.capacity
	if rb.size < rb.capacity {
		rb.size++
	}

	return droppedMat, dropped
}

// GetLast returns the last N frames (up to duration)
// It returns COPIES (clones) of the Mats because the buffer keeps the originals
// and might overwrite them. Or we can return the frames and clear the buffer?
// Strategy: When motion is detected, we want to dump the buffer.
// So we can return all frames and CLEAR the buffer (transfer ownership).
func (rb *RingBuffer) Flush() []Frame {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	if rb.size == 0 {
		return nil
	}

	result := make([]Frame, 0, rb.size)
	
	// Iterate from oldest to newest
	// Head points to the next write slot, so (head - size) is the oldest
	idx := (rb.head - rb.size + rb.capacity) % rb.capacity
	
	for i := 0; i < rb.size; i++ {
		result = append(result, rb.frames[idx])
		// We transfer ownership, so we nil out the Mat in the buffer to avoid double close
		rb.frames[idx] = Frame{} 
		idx = (idx + 1) % rb.capacity
	}

	rb.size = 0
	rb.head = 0
	return result
}
