package pipeline

import (
	"time"
	"gocv.io/x/gocv"
)

// Frame represents a video frame passing through the pipeline
type Frame struct {
	ID        int
	Mat       gocv.Mat
	Timestamp time.Time
}
