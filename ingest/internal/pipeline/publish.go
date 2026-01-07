package pipeline

import (

	"fmt"
	"log"
	"sync/atomic"

	"github.com/nats-io/nats.go"
)

var FramesSent uint64

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



		err := nc.PublishMsg(natsMsg)
		if err != nil {
			log.Printf("Error publishing to NATS subject '%s': %v", subject, err)
		} else {
			atomic.AddUint64(&FramesSent, 1)
		}
	}
}
