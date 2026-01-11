package pipeline

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"sync/atomic"
	"time"

	"github.com/nats-io/nats.go"
)

var FramesSent uint64

// ConfigCache stores hash and last sent time for each camera config
type ConfigCache struct {
	lastHash   string
	lastSent   time.Time
	configData string // JSON string
	mu         sync.RWMutex
}

var configCaches = make(map[string]*ConfigCache) // camera_id -> cache
var configCacheMutex sync.RWMutex

const configSyncPeriod = 60 * time.Second // Re-sync every 60s

func getConfigCache(cameraID string) *ConfigCache {
	configCacheMutex.RLock()
	cache, exists := configCaches[cameraID]
	configCacheMutex.RUnlock()

	if !exists {
		configCacheMutex.Lock()
		cache = &ConfigCache{}
		configCaches[cameraID] = cache
		configCacheMutex.Unlock()
	}

	return cache
}

func PublishWorker(nc *nats.Conn, in <-chan Message) {
	for msg := range in {
		// Build NATS subject with multi-tenancy support
		var subject string
		if msg.OrgSlug != "" && msg.ZoneSlug != "" {
			// New multi-tenant format: org.{org}.zone.{zone}.camera.{id}.frame
			subject = fmt.Sprintf("org.%s.zone.%s.camera.%s.frame", msg.OrgSlug, msg.ZoneSlug, msg.CameraID)
		} else {
			// Legacy format: camera.{id}.frame
			subject = fmt.Sprintf("camera.%s.frame", msg.CameraID)
		}

		natsMsg := nats.NewMsg(subject)
		natsMsg.Data = msg.Data
		natsMsg.Header.Add("Timestamp", fmt.Sprintf("%d", msg.Timestamp))
		natsMsg.Header.Add("camera_id", msg.CameraID)

		// Add multi-tenancy headers if available
		if msg.OrgSlug != "" {
			natsMsg.Header.Add("org_slug", msg.OrgSlug)
		}
		if msg.ZoneSlug != "" {
			natsMsg.Header.Add("zone_slug", msg.ZoneSlug)
		}

		// ✅ CONFIG CACHING WITH HASH
		// Only send full config if hash changed or sync period elapsed
		if configData, err := json.Marshal(msg.Config); err == nil {
			configJSON := string(configData)

			// Calculate MD5 hash
			hash := md5.Sum([]byte(configJSON))
			configHash := hex.EncodeToString(hash[:])

			cache := getConfigCache(msg.CameraID)
			cache.mu.Lock()

			shouldSendFull := false
			if cache.lastHash != configHash {
				// Config changed
				shouldSendFull = true
				log.Printf("📤 Config changed for camera %s (hash: %s)", msg.CameraID, configHash[:8])
			} else if time.Since(cache.lastSent) > configSyncPeriod {
				// Periodic re-sync (prevent desync)
				shouldSendFull = true
				log.Printf("🔄 Config re-sync for camera %s (60s elapsed)", msg.CameraID)
			}

			if shouldSendFull {
				// Send full config + hash
				natsMsg.Header.Add("Config-Data", configJSON)
				natsMsg.Header.Add("Config-Hash", configHash)
				cache.lastHash = configHash
				cache.configData = configJSON
				cache.lastSent = time.Now()
			} else {
				// Send only hash (inference will use cached config)
				natsMsg.Header.Add("Config-Hash", configHash)
			}

			cache.mu.Unlock()
		}

		err := nc.PublishMsg(natsMsg)
		if err != nil {
			log.Printf("Error publishing to NATS subject '%s': %v", subject, err)
		} else {
			atomic.AddUint64(&FramesSent, 1)
		}
	}
}