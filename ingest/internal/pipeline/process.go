package pipeline

import (
	"fmt"
	"image"
	"log"
	"sync"
	"sync/atomic"

	"time"
	"vigias-ia/ingest/internal/config"

	"gocv.io/x/gocv"
)

// Message to be published
type Message struct {
	CameraID  string
	OrgSlug   string // Multi-tenancy: organization slug
	ZoneSlug  string // Multi-tenancy: zone slug
	Data      []byte
	Timestamp int64 // Unix Nano
	Config    config.CameraConfig
}

func ProcessWorker(cam config.CameraConfig, cfg *config.Config, in <-chan Frame, out chan<- Message) {
	defer close(out)

	imgResized := gocv.NewMat()
	defer imgResized.Close()

	// MOG2 Background Subtractor - Optimized: detectShadows=false
	mog2 := gocv.NewBackgroundSubtractorMOG2WithParams(500, 16, false)
	defer mog2.Close()

	fgMask := gocv.NewMat()
	defer fgMask.Close()

	// Ring Buffer for Pre-Event Recording (2 seconds)
	bufferSize := int(cfg.TargetFPS * 2)
	ringBuffer := NewRingBuffer(bufferSize)

	// Mat Pool to reduce GC pressure and allocations
	// We pre-allocate Mats of the correct size and type (CV_8UC3)
	matPool := &sync.Pool{
		New: func() interface{} {
			return gocv.NewMat()
		},
	}

	fmt.Printf("[%s] Process Worker Started (MOG2 Optimized)\n", cam.ID)

	var lastMotionTime time.Time
	postMotionDuration := 5 * time.Second

	for frame := range in {
		// 1. Resize (Letterbox)
		// Logic ported from legacy sizing.py: Scale to fit within target box, pad with grey.

		// ✅ Use per-camera resize settings (dynamic based on use case)
		// Priority: Camera-specific > Global config
		resizeWidth := cam.ResizeWidth
		resizeHeight := cam.ResizeHeight
		if resizeWidth == 0 {
			resizeWidth = cfg.ResizeWidth
		}
		if resizeHeight == 0 {
			resizeHeight = cfg.ResizeHeight
		}

		targetW, targetH := float64(resizeWidth), float64(resizeHeight)
		origRows, origCols := frame.Mat.Rows(), frame.Mat.Cols()
		origH, origW := float64(origRows), float64(origCols)
		
		scale := min(targetH/origH, targetW/origW)
		nw, nh := int(origW*scale), int(origH*scale)
		
		// Resize original to new scaled dimensions
		scaled := gocv.NewMat()
		gocv.Resize(frame.Mat, &scaled, image.Pt(nw, nh), 0, 0, gocv.InterpolationLinear)
		
		// Create target canvas (grey background)
		// Re-use imgResized if possible, but for simplicity of letterboxing logic involving ROIs,
		// we might need to be careful. imgResized is our target 'canvas'.
		// Reset canvas to grey (128)
		imgResized.SetTo(gocv.NewScalar(128, 128, 128, 0))
		
		// Make sure imgResized is the correct size first (it should be initialized once or reused)
		if imgResized.Cols() != resizeWidth || imgResized.Rows() != resizeHeight {
			// Re-allocate if size changed (or first run)
			imgResized.Close()
			imgResized = gocv.NewMatWithSize(resizeHeight, resizeWidth, gocv.MatTypeCV8UC3)
			imgResized.SetTo(gocv.NewScalar(128, 128, 128, 0))
		} else {
             // Just clear it
             imgResized.SetTo(gocv.NewScalar(128, 128, 128, 0))
        }
		
		// Paste scaled image into center
		top := (int(targetH) - nh) / 2
		left := (int(targetW) - nw) / 2
		
		// Define ROI on canvas
		roi := imgResized.Region(image.Rect(left, top, left+nw, top+nh))
		scaled.CopyTo(&roi)
		
		scaled.Close()
		roi.Close()


		// Update FrameHub for Streaming/Snapshots
		// We use imgResized (which is the standardized size)
		Hub.UpdateFrame(cam.ID, imgResized)

		// 2. Motion Gating (MOG2)
		mog2.Apply(imgResized, &fgMask)

		nonZero := gocv.CountNonZero(fgMask)
		totalPixels := resizeWidth * resizeHeight
		changePct := float64(nonZero) / float64(totalPixels)

		// Get a Mat from the pool
		pooledMat := matPool.Get().(gocv.Mat)
		imgResized.CopyTo(&pooledMat) // Deep copy into pooled Mat

		// Add to RingBuffer
		// We need to handle the "dropped" frame from the RingBuffer (if it overwrote one)
		// The RingBuffer logic needs to return the dropped Mat so we can Put it back in the pool.
		droppedMat, dropped := ringBuffer.Add(Frame{Mat: pooledMat, Timestamp: frame.Timestamp})
		if dropped {
			matPool.Put(droppedMat)
		}

		isMotion := changePct >= cfg.MotionThresh

		if isMotion {
			lastMotionTime = time.Now()
		}

		// Send frame if motion detected OR within post-motion window
		if isMotion || time.Since(lastMotionTime) < postMotionDuration {

			// Flush buffer (send pre-event frames) if this is a NEW motion event
			// Logic: If we were NOT sending, and now we are, flush buffer.
			// But simpler: Just flush buffer whenever we send, but RingBuffer handles "already flushed" logic?
			// No, RingBuffer flush clears it.

			// Better Logic:
			// If motion detected, flush buffer immediately to catch start of event.
			if isMotion {
				preEventFrames := ringBuffer.Flush()
				for _, f := range preEventFrames {
					sendFrame(cam, f.Mat, f.Timestamp, out)
					matPool.Put(f.Mat)
				}
			}

			// Send current frame
			// We need to clone it because sendFrame is async? No, sendFrame encodes immediately.
			// But we put it in RingBuffer which might hold it.
			// Actually, we already put it in RingBuffer.
			// If we flush, we get it back? No, RingBuffer.Add adds it.
			// If we are in "recording mode", we should just send the current frame.
			// But wait, if we added it to RingBuffer, we need to be careful not to double send or leak.

			// WAIT. If we send it now, and later it gets flushed/dropped, we are fine.
			// BUT if we send it now, we don't want to send it AGAIN when flushing?
			// If we are in "recording mode", we flush the buffer once at the start.
			// Then we just send incoming frames.

			// Refined Logic:
			// We need state: are we currently "recording"?
			// If !recording and Motion: Start Recording -> Flush Buffer -> Send Current.
			// If recording: Send Current.

			// But we don't have explicit state variable here easily without refactoring loop.
			// Let's use time check.

			// Actually, simply:
			// If isMotion: Flush Buffer (returns frames including current if added? No, usually previous).
			// If RingBuffer.Add adds to HEAD, then Flush returns everything.

			// Let's assume Flush returns everything currently in buffer.
			// If we just added current frame, Flush returns it.
			// So if isMotion, Flush sends everything.
			// If !isMotion but within Duration:
			//    We still need to send. But RingBuffer has it.
			//    We should Flush it?

			// Correct approach with RingBuffer:
			// RingBuffer is for *waiting* frames.
			// If we are "active", we shouldn't be buffering, we should be passing through.
			// But we need to keep buffering for the *next* event?
			// No, if we are active, we just send.

			// Let's change the pattern:
			// Always add to RingBuffer.
			// If Active (Motion or Cooldown):
			//    Flush RingBuffer and send ALL frames in it.
			//    This ensures order and no duplicates.

			preEventFrames := ringBuffer.Flush()
			for _, f := range preEventFrames {
				sendFrame(cam, f.Mat, f.Timestamp, out)
				matPool.Put(f.Mat)
			}

		} else {
			// No motion and cooldown expired.
			// Frame stays in buffer (waiting for future motion).
			atomic.AddUint64(&FramesDropped, 1)
		}

		frame.Mat.Close() // Close original capture frame
	}
}

func sendFrame(cam config.CameraConfig, mat gocv.Mat, ts time.Time, out chan<- Message) {
	// Optimize JPEG quality for speed/size balance (80 is usually a good sweet spot)
	buf, err := gocv.IMEncodeWithParams(gocv.JPEGFileExt, mat, []int{int(gocv.IMWriteJpegQuality), 80})
	if err != nil {
		log.Printf("Error encoding image: %v", err)
		return
	}

	out <- Message{
		CameraID:  cam.ID,
		OrgSlug:   cam.OrgSlug,
		ZoneSlug:  cam.ZoneSlug,
		Data:      buf.GetBytes(),
		Timestamp: ts.UnixNano(),
		Config:    cam,
	}
	buf.Close()
}