"""
Event Handler Service

Listens to NATS events.alarm messages from inference service
and triggers notification rule evaluation.

Flow:
1. Inference service detects event (intrusion, face recognition, etc.)
2. Publishes to events.alarm NATS subject
3. EventHandler receives message
4. Creates Event record in database
5. Triggers NotificationRuleEngine
6. Notifications sent automatically
"""
import logging
import json
from datetime import datetime
from nats.aio.client import Client as NATSClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models import Event
from app.services.notification_rule_engine import trigger_notification_rules
from app.core.metrics import track_event_created

logger = logging.getLogger("router.event_handler")


class EventHandler:
    """
    Handles incoming alarm events from inference service and creates
    Event records + triggers notification rules.
    """

    def __init__(self, nc: NATSClient):
        self.nc = nc

    async def start_listening(self):
        """
        Subscribe to events.alarm NATS subject and process incoming events.
        """
        await self.nc.subscribe("events.alarm", cb=self.handle_event)
        logger.info("EventHandler subscribed to 'events.alarm' subject")

    async def handle_event(self, msg):
        """
        Process incoming alarm event from NATS.

        Expected message format (JSON):
        {
            "camera_id": "uuid",
            "event_type": "intrusion" | "license_plate" | "security_alert" | etc,
            "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
            "message": "Human-readable message",
            "track_id": "optional track ID",
            "timestamp": 1234567890.123,
            "confidence": 0.95,
            "metadata": {...}
        }
        """
        try:
            # Parse message
            data = json.loads(msg.data.decode())

            logger.info(f"Received alarm event: type={data.get('event_type')}, severity={data.get('severity')}, camera={data.get('camera_id')}")

            # Create Event in database
            async with AsyncSessionLocal() as db:
                event = await self._create_event(db, data)

                if not event:
                    logger.warning("Failed to create event, skipping notification evaluation")
                    return

                # Trigger notification rules
                results = await trigger_notification_rules(event.id, db)

                if results:
                    logger.info(f"Event {event.id}: {len(results)} notification(s) processed")
                    for result in results:
                        if result.get("status") == "SENT":
                            logger.info(f"  ✅ Sent via {result.get('channel_type')} to {result.get('recipient')}")
                        elif result.get("status") == "skipped":
                            logger.debug(f"  ⏭️  Skipped: {result.get('reason')}")
                        elif result.get("status") == "failed":
                            logger.error(f"  ❌ Failed: {result.get('error', result.get('reason'))}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse alarm event JSON: {e}")
        except Exception as e:
            logger.error(f"Error handling alarm event: {e}", exc_info=True)

    async def _create_event(self, db: AsyncSession, data: dict) -> Event:
        """
        Create Event record from alarm data.

        Args:
            db: Database session
            data: Alarm event data from NATS

        Returns:
            Created Event instance or None if creation failed
        """
        try:
            # Extract fields from alarm data
            camera_id = data.get("camera_id")
            if not camera_id:
                logger.error("Alarm event missing camera_id")
                return None

            event_type = data.get("event_type", "unknown")
            severity = data.get("severity", "MEDIUM").upper()

            # Validate severity
            valid_severities = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
            if severity not in valid_severities:
                logger.warning(f"Invalid severity '{severity}', defaulting to MEDIUM")
                severity = "MEDIUM"

            # Create event
            event = Event(
                camera_id=camera_id,
                event_type=event_type,
                severity=severity,
                status="PENDING",  # New events start as PENDING
                track_id=data.get("track_id"),
                confidence=data.get("confidence"),
                occurred_at=datetime.fromtimestamp(data.get("timestamp", datetime.now().timestamp())),
                # Note: snapshot_path and video_clip_path would be set by inference service
                # if they save clips/snapshots for events
            )

            db.add(event)
            await db.commit()
            await db.refresh(event)

            # Track metrics
            track_event_created(event_type=event_type, severity=severity)

            logger.info(f"Created event {event.id}: {event_type} ({severity}) on camera {camera_id}")
            return event

        except Exception as e:
            logger.error(f"Failed to create event record: {e}", exc_info=True)
            await db.rollback()
            return None


# Global event handler instance (initialized in main.py)
event_handler: EventHandler = None


def get_event_handler() -> EventHandler:
    """Get the global event handler instance"""
    return event_handler


def set_event_handler(handler: EventHandler):
    """Set the global event handler instance"""
    global event_handler
    event_handler = handler
