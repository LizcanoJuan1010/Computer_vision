"""
Notification Rule Evaluation Engine

Automatically evaluates notification rules when events are created
and sends notifications through configured channels.

Flow:
1. Event created in database
2. Engine evaluates all active rules
3. Matches rules against event criteria (type, severity, camera, zone)
4. Checks cooldown period to prevent spam
5. Sends notifications through matched channels
6. Logs notification delivery status
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models import (
    Event,
    NotificationRule,
    NotificationChannel,
    NotificationLog,
    Camera,
    OrgZone
)
from app.services.notification_sender import notification_sender

logger = logging.getLogger("router.notification_rule_engine")


class NotificationRuleEngine:
    """
    Engine for evaluating notification rules and sending notifications.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def evaluate_event(self, event: Event) -> List[Dict[str, Any]]:
        """
        Evaluate all notification rules against an event and send notifications.

        Args:
            event: The event to evaluate

        Returns:
            List of notification results (sent, failed, skipped)
        """
        results = []

        # Get event's camera and zone for filtering
        camera = await self.db.get(Camera, event.camera_id)
        if not camera:
            logger.warning(f"Event {event.id} has no associated camera")
            return results

        zone = await self.db.get(OrgZone, camera.zone_id) if camera.zone_id else None
        organization_id = zone.organization_id if zone else None

        if not organization_id:
            logger.warning(f"Event {event.id} has no organization context")
            return results

        # Fetch all active rules for this organization
        query = select(NotificationRule).where(
            and_(
                NotificationRule.organization_id == organization_id,
                NotificationRule.is_active == True
            )
        )
        result = await self.db.execute(query)
        rules = result.scalars().all()

        logger.info(f"Evaluating {len(rules)} rules for event {event.id} (type={event.event_type}, severity={event.severity})")

        # Evaluate each rule
        for rule in rules:
            evaluation_result = await self._evaluate_rule(rule, event, camera, zone)
            if evaluation_result:
                results.append(evaluation_result)

        return results

    async def _evaluate_rule(
        self,
        rule: NotificationRule,
        event: Event,
        camera: Camera,
        zone: Optional[OrgZone]
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a single rule against an event.

        Args:
            rule: The notification rule to evaluate
            event: The event being processed
            camera: The camera associated with the event
            zone: The zone associated with the camera

        Returns:
            Notification result dict or None if rule doesn't match
        """
        # Check if rule matches event criteria
        if not self._rule_matches_event(rule, event, camera, zone):
            logger.debug(f"Rule {rule.id} ({rule.name}) does not match event {event.id}")
            return None

        # Check cooldown period
        if await self._is_in_cooldown(rule):
            logger.info(f"Rule {rule.id} ({rule.name}) is in cooldown period, skipping")
            return {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "status": "skipped",
                "reason": "cooldown_active"
            }

        # Check active schedule (if configured)
        if not self._is_within_schedule(rule):
            logger.debug(f"Rule {rule.id} ({rule.name}) outside active schedule")
            return {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "status": "skipped",
                "reason": "outside_schedule"
            }

        # Fetch notification channel
        channel = await self.db.get(NotificationChannel, rule.channel_id)
        if not channel or not channel.is_active:
            logger.warning(f"Rule {rule.id} has inactive/missing channel {rule.channel_id}")
            return {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "status": "failed",
                "reason": "channel_inactive"
            }

        # Send notification
        return await self._send_notification(rule, channel, event, camera, zone)

    def _rule_matches_event(
        self,
        rule: NotificationRule,
        event: Event,
        camera: Camera,
        zone: Optional[OrgZone]
    ) -> bool:
        """
        Check if a rule matches an event based on configured criteria.

        Criteria:
        - event_types: List of event types to match (e.g., ['intrusion', 'loitering'])
        - severities: List of severities to match (e.g., ['CRITICAL', 'HIGH'])
        - camera_ids: List of specific camera IDs to match
        - zone_ids: List of specific zone IDs to match

        If a criterion is None or empty, it matches all.
        """
        # Check event type
        if rule.event_types and event.event_type not in rule.event_types:
            return False

        # Check severity
        if rule.severities and event.severity not in rule.severities:
            return False

        # Check camera ID
        if rule.camera_ids:
            camera_ids_str = [str(cid) for cid in rule.camera_ids]
            if str(camera.id) not in camera_ids_str:
                return False

        # Check zone ID
        if rule.zone_ids and zone:
            zone_ids_str = [str(zid) for zid in rule.zone_ids]
            if str(zone.id) not in zone_ids_str:
                return False

        return True

    async def _is_in_cooldown(self, rule: NotificationRule) -> bool:
        """
        Check if a rule is in cooldown period (to prevent notification spam).

        Args:
            rule: The notification rule

        Returns:
            True if in cooldown, False otherwise
        """
        if rule.cooldown_minutes <= 0:
            return False

        # Find last notification sent by this rule
        query = (
            select(NotificationLog)
            .where(NotificationLog.rule_id == rule.id)
            .order_by(NotificationLog.sent_at.desc())
            .limit(1)
        )
        result = await self.db.execute(query)
        last_log = result.scalar_one_or_none()

        if not last_log:
            return False

        # Check if cooldown period has passed
        cooldown_expires = last_log.sent_at + timedelta(minutes=rule.cooldown_minutes)
        return datetime.now() < cooldown_expires

    def _is_within_schedule(self, rule: NotificationRule) -> bool:
        """
        Check if current time is within the rule's active schedule.

        active_schedule format (example):
        {
            "enabled": true,
            "days": ["MON", "TUE", "WED", "THU", "FRI"],
            "time_start": "08:00",
            "time_end": "18:00"
        }

        Args:
            rule: The notification rule

        Returns:
            True if within schedule or no schedule configured
        """
        if not rule.active_schedule or not rule.active_schedule.get("enabled"):
            return True

        now = datetime.now()

        # Check day of week
        days = rule.active_schedule.get("days", [])
        if days:
            current_day = now.strftime("%a").upper()
            day_map = {"MON": "MON", "TUE": "TUE", "WED": "WED", "THU": "THU", "FRI": "FRI", "SAT": "SAT", "SUN": "SUN"}
            if current_day not in days:
                return False

        # Check time range
        time_start = rule.active_schedule.get("time_start")
        time_end = rule.active_schedule.get("time_end")

        if time_start and time_end:
            current_time = now.time()
            from datetime import time as dt_time

            start_time = dt_time(*map(int, time_start.split(":")))
            end_time = dt_time(*map(int, time_end.split(":")))

            if not (start_time <= current_time <= end_time):
                return False

        return True

    async def _send_notification(
        self,
        rule: NotificationRule,
        channel: NotificationChannel,
        event: Event,
        camera: Camera,
        zone: Optional[OrgZone]
    ) -> Dict[str, Any]:
        """
        Send notification through the configured channel.

        Args:
            rule: The notification rule
            channel: The notification channel
            event: The event triggering the notification
            camera: The camera associated with the event
            zone: The zone (if any)

        Returns:
            Notification result dict
        """
        # Determine recipient from channel config
        recipient = channel.config.get("default_recipient", "")
        if not recipient:
            logger.error(f"Channel {channel.id} has no default_recipient configured")
            return {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "channel_id": str(channel.id),
                "status": "failed",
                "reason": "no_recipient_configured"
            }

        # Build notification message
        subject = self._build_subject(rule, event, camera, zone)
        message = self._build_message(rule, event, camera, zone)
        metadata = self._build_metadata(event, camera, zone)

        try:
            # Send notification using notification sender service
            result = await notification_sender.send(
                channel_type=channel.channel_type,
                channel_config=channel.config,
                recipient=recipient,
                subject=subject,
                message=message,
                metadata=metadata
            )

            # Log notification
            log = NotificationLog(
                rule_id=rule.id,
                event_id=event.id,
                channel_type=channel.channel_type,
                recipient=recipient,
                status=result["status"],
                error_message=result.get("error_message"),
                sent_at=result["sent_at"]
            )
            self.db.add(log)
            await self.db.commit()

            logger.info(f"Notification sent: rule={rule.name}, channel={channel.channel_type}, status={result['status']}")

            return {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "channel_id": str(channel.id),
                "channel_type": channel.channel_type,
                "status": result["status"],
                "delivery_time_ms": result["delivery_time_ms"],
                "recipient": recipient
            }

        except Exception as e:
            logger.error(f"Failed to send notification for rule {rule.id}: {e}")

            # Log failure
            log = NotificationLog(
                rule_id=rule.id,
                event_id=event.id,
                channel_type=channel.channel_type,
                recipient=recipient,
                status="FAILED",
                error_message=str(e),
                sent_at=datetime.now()
            )
            self.db.add(log)
            await self.db.commit()

            return {
                "rule_id": str(rule.id),
                "rule_name": rule.name,
                "channel_id": str(channel.id),
                "status": "failed",
                "error": str(e)
            }

    def _build_subject(
        self,
        rule: NotificationRule,
        event: Event,
        camera: Camera,
        zone: Optional[OrgZone]
    ) -> str:
        """Build notification subject line"""
        severity_emoji = {
            "CRITICAL": "🚨",
            "HIGH": "⚠️",
            "MEDIUM": "⚡",
            "LOW": "ℹ️",
            "INFO": "📢"
        }
        emoji = severity_emoji.get(event.severity, "🔔")

        zone_name = zone.name if zone else "Unknown Zone"
        return f"{emoji} {event.severity} Alert: {event.event_type} at {zone_name}"

    def _build_message(
        self,
        rule: NotificationRule,
        event: Event,
        camera: Camera,
        zone: Optional[OrgZone]
    ) -> str:
        """Build notification message body"""
        zone_name = zone.name if zone else "Unknown Zone"
        camera_location = camera.location_name or camera.name

        message = f"""
VIGIAS-IA Security Alert

Event Type: {event.event_type}
Severity: {event.severity}
Status: {event.status}

Location:
  Zone: {zone_name}
  Camera: {camera_location}

Details:
  Event ID: {event.id}
  Confidence: {event.confidence * 100 if event.confidence else 'N/A'}%
  Occurred At: {event.occurred_at.strftime('%Y-%m-%d %H:%M:%S')}

Notification Rule: {rule.name}
"""

        if event.track_id:
            message += f"  Track ID: {event.track_id}\n"

        if rule.description:
            message += f"\nRule Description: {rule.description}\n"

        return message.strip()

    def _build_metadata(
        self,
        event: Event,
        camera: Camera,
        zone: Optional[OrgZone]
    ) -> Dict[str, Any]:
        """Build metadata for rich notifications (webhooks, Slack, etc.)"""
        return {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "severity": event.severity,
            "status": event.status,
            "confidence": float(event.confidence) if event.confidence else None,
            "camera": {
                "id": str(camera.id),
                "name": camera.name,
                "location": camera.location_name
            },
            "zone": {
                "id": str(zone.id),
                "name": zone.name
            } if zone else None,
            "occurred_at": event.occurred_at.isoformat(),
            "snapshot_url": f"/api/v1/events/{event.id}/snapshot" if event.snapshot_path else None,
            "video_url": f"/api/v1/events/{event.id}/video" if event.video_clip_path else None
        }


async def trigger_notification_rules(event_id: UUID, db: AsyncSession) -> List[Dict[str, Any]]:
    """
    Helper function to trigger notification rule evaluation for an event.

    This should be called after creating an event in the database.

    Args:
        event_id: UUID of the event to evaluate
        db: Database session

    Returns:
        List of notification results

    Usage:
        # After creating event
        event = Event(...)
        db.add(event)
        await db.commit()

        # Trigger notifications
        results = await trigger_notification_rules(event.id, db)
    """
    event = await db.get(Event, event_id)
    if not event:
        logger.error(f"Event {event_id} not found for notification evaluation")
        return []

    engine = NotificationRuleEngine(db)
    results = await engine.evaluate_event(event)

    logger.info(f"Notification evaluation complete for event {event_id}: {len(results)} notifications processed")
    return results
