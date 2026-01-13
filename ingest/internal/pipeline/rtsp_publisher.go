package pipeline

import (
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"sync"

	"gocv.io/x/gocv"
)

// RTSPPublisher handles pushing frames to MediaMTX via RTSP using FFmpeg
type RTSPPublisher struct {
	cameraID string
	rtspURL  string
	cmd      *exec.Cmd
	stdin    io.WriteCloser
	mu       sync.Mutex
	running  bool
}

// NewRTSPPublisher creates a new publisher for a specific camera
func NewRTSPPublisher(cameraID string) *RTSPPublisher {
	// Push to MediaMTX. Assumes MediaMTX is named "mediamtx" in docker network
	url := fmt.Sprintf("rtsp://mediamtx:8554/%s", cameraID)
	return &RTSPPublisher{
		cameraID: cameraID,
		rtspURL:  url,
	}
}

// Start launches the FFmpeg process
func (p *RTSPPublisher) Start() error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if p.running {
		return nil
	}

	// FFmpeg command to read MJPEG from stdin and push RTSP
	// -re: Read input at native frame rate (important for live stream)
	// -f image2pipe: Input format is a pipe of images
	// -vcodec mjpeg: Input codec is MJPEG
	// -i -: Read from stdin
	// -c:v copy: Copy video stream (no transcoding if possible, but MJPEG -> H264 might be needed for some players)
	// Actually, MediaMTX handles many formats. Let's try raw MJPEG copy first for speed.
	// If WebRTC needs H264, we might need to transcode. 
	// WebRTC usually requires H264 or VP8. MJPEG might not work directly in WebRTC without transcoding.
	// Let's Transcode to H264 using libx264 for maximum compatibility.
	// -preset ultrafast: Minimize latency
	// -tune zerolatency: Minimize latency
	// -f rtsp: Output format
	
	args := []string{
		"-y",
		"-f", "image2pipe",
		"-vcodec", "mjpeg",
		"-i", "-",
		"-c:v", "libx264",
		"-preset", "ultrafast",
		"-tune", "zerolatency",
		"-pix_fmt", "yuv420p", // Required for compatibility
		"-profile:v", "baseline", // CRITICAL: WebRTC often fails with High profile, Baseline ensures browser compatibility
		"-level", "3.0",
		"-f", "rtsp",
		"-rtsp_transport", "tcp",
		p.rtspURL,
	}

	cmd := exec.Command("ffmpeg", args...)
	
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return fmt.Errorf("failed to get stdin pipe: %v", err)
	}

	// Log FFmpeg output for debugging (optional, can be noisy)
	// cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("failed to start ffmpeg: %v", err)
	}

	p.cmd = cmd
	p.stdin = stdin
	p.running = true
	
	log.Printf("[RTSPPublisher] Started pushing to %s", p.rtspURL)
	
	// Monitor process in background
	go func() {
		err := cmd.Wait()
		p.mu.Lock()
		p.running = false
		p.mu.Unlock()
		if err != nil {
			log.Printf("[RTSPPublisher] FFmpeg exited with error: %v", err)
		} else {
			log.Printf("[RTSPPublisher] FFmpeg exited normally")
		}
	}()

	return nil
}

// WriteFrame encodes frame to JPEG and writes to FFmpeg stdin
func (p *RTSPPublisher) WriteFrame(img gocv.Mat) error {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.running {
		return fmt.Errorf("publisher not running")
	}

	// Encodes to JPEG
	buf, err := gocv.IMEncode(".jpg", img)
	if err != nil {
		return err
	}
	defer buf.Close()

	// Write bytes
	_, err = p.stdin.Write(buf.GetBytes())
	if err != nil {
		return err
	}
	
	return nil
}

// Stop terminates the FFmpeg process
func (p *RTSPPublisher) Stop() {
	p.mu.Lock()
	defer p.mu.Unlock()

	if !p.running {
		return
	}

	if p.stdin != nil {
		p.stdin.Close()
	}

	if p.cmd != nil && p.cmd.Process != nil {
		p.cmd.Process.Kill()
	}

	p.running = false
	log.Printf("[RTSPPublisher] Stopped pushing %s", p.cameraID)
}
