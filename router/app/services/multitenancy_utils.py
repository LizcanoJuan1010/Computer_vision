"""
Multi-tenancy utility functions for Redis cache keys and NATS subjects
"""
from typing import Optional
from uuid import UUID


def build_redis_cache_key(
    camera_id: str,
    org_slug: Optional[str] = None,
    zone_slug: Optional[str] = None
) -> str:
    """
    Builds Redis cache key with multi-tenancy support.

    New format: config:org:{org_slug}:zone:{zone_slug}:camera:{camera_id}
    Legacy format: config:camera:{camera_id}

    Args:
        camera_id: Camera identifier (UUID string or legacy ID)
        org_slug: Organization slug (optional for backward compatibility)
        zone_slug: Zone slug (optional for backward compatibility)

    Returns:
        Redis key string

    Examples:
        >>> build_redis_cache_key("cam_1", "acme-corp", "warehouse")
        "config:org:acme-corp:zone:warehouse:camera:cam_1"

        >>> build_redis_cache_key("cam_1")  # Legacy
        "config:camera:cam_1"
    """
    if org_slug and zone_slug:
        return f"config:org:{org_slug}:zone:{zone_slug}:camera:{camera_id}"
    else:
        # Legacy format for backward compatibility
        return f"config:camera:{camera_id}"


def build_nats_subject(
    camera_id: str,
    event_type: str = "frame",
    org_slug: Optional[str] = None,
    zone_slug: Optional[str] = None
) -> str:
    """
    Builds NATS subject with multi-tenancy support.

    New format: org.{org_slug}.zone.{zone_slug}.camera.{camera_id}.{event_type}
    Legacy format: camera.{camera_id}.{event_type}

    Args:
        camera_id: Camera identifier
        event_type: Type of event (frame, alarm, config, etc.)
        org_slug: Organization slug (optional for backward compatibility)
        zone_slug: Zone slug (optional for backward compatibility)

    Returns:
        NATS subject string

    Examples:
        >>> build_nats_subject("cam_1", "frame", "acme-corp", "warehouse")
        "org.acme-corp.zone.warehouse.camera.cam_1.frame"

        >>> build_nats_subject("cam_1", "frame")  # Legacy
        "camera.cam_1.frame"
    """
    if org_slug and zone_slug:
        return f"org.{org_slug}.zone.{zone_slug}.camera.{camera_id}.{event_type}"
    else:
        # Legacy format for backward compatibility
        return f"camera.{camera_id}.{event_type}"


def build_nats_wildcard_subject(
    org_slug: Optional[str] = None,
    zone_slug: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_type: Optional[str] = None
) -> str:
    """
    Builds NATS wildcard subject for subscriptions with multi-tenancy support.

    Args:
        org_slug: Organization slug (None = wildcard *)
        zone_slug: Zone slug (None = wildcard *)
        camera_id: Camera identifier (None = wildcard *)
        event_type: Event type (None = wildcard *)

    Returns:
        NATS wildcard subject string

    Examples:
        >>> build_nats_wildcard_subject()  # All events
        "camera.*.frame"  # Legacy for now

        >>> build_nats_wildcard_subject("acme-corp")  # All cameras in org
        "org.acme-corp.zone.*.camera.*.frame"

        >>> build_nats_wildcard_subject("acme-corp", "warehouse")  # All cameras in zone
        "org.acme-corp.zone.warehouse.camera.*.frame"

        >>> build_nats_wildcard_subject("acme-corp", "warehouse", event_type="alarm")
        "org.acme-corp.zone.warehouse.camera.*.alarm"
    """
    if org_slug:
        # New multi-tenancy format
        org_part = org_slug
        zone_part = zone_slug or "*"
        camera_part = camera_id or "*"
        event_part = event_type or "frame"
        return f"org.{org_part}.zone.{zone_part}.camera.{camera_part}.{event_part}"
    else:
        # Legacy format (default to backward compatibility)
        camera_part = camera_id or "*"
        event_part = event_type or "frame"
        return f"camera.{camera_part}.{event_part}"


def parse_nats_subject(subject: str) -> dict:
    """
    Parses a NATS subject to extract org, zone, camera, and event type.

    Supports both new and legacy formats.

    Args:
        subject: NATS subject string

    Returns:
        Dictionary with org_slug, zone_slug, camera_id, event_type

    Examples:
        >>> parse_nats_subject("org.acme-corp.zone.warehouse.camera.cam_1.frame")
        {
            "org_slug": "acme-corp",
            "zone_slug": "warehouse",
            "camera_id": "cam_1",
            "event_type": "frame",
            "is_legacy": False
        }

        >>> parse_nats_subject("camera.cam_1.frame")
        {
            "org_slug": None,
            "zone_slug": None,
            "camera_id": "cam_1",
            "event_type": "frame",
            "is_legacy": True
        }
    """
    parts = subject.split('.')

    # Check if it's new multi-tenancy format
    if parts[0] == "org" and len(parts) >= 7:
        # Format: org.{org}.zone.{zone}.camera.{cam}.{event}
        return {
            "org_slug": parts[1],
            "zone_slug": parts[3],
            "camera_id": parts[5],
            "event_type": parts[6] if len(parts) > 6 else "frame",
            "is_legacy": False
        }
    elif parts[0] == "camera" and len(parts) >= 2:
        # Legacy format: camera.{cam}.{event}
        return {
            "org_slug": None,
            "zone_slug": None,
            "camera_id": parts[1],
            "event_type": parts[2] if len(parts) > 2 else "frame",
            "is_legacy": True
        }
    else:
        # Unknown format
        return {
            "org_slug": None,
            "zone_slug": None,
            "camera_id": None,
            "event_type": None,
            "is_legacy": False
        }


def build_alarm_subject(
    org_slug: str,
    zone_slug: Optional[str] = None,
    camera_id: Optional[str] = None
) -> str:
    """
    Builds NATS subject for alarm events.

    Format: org.{org_slug}.events.alarm or org.{org_slug}.zone.{zone}.camera.{cam}.alarm

    Args:
        org_slug: Organization slug
        zone_slug: Optional zone slug (for zone-specific alarms)
        camera_id: Optional camera ID (for camera-specific alarms)

    Returns:
        NATS subject for alarms

    Examples:
        >>> build_alarm_subject("acme-corp")  # Org-wide alarms
        "org.acme-corp.events.alarm"

        >>> build_alarm_subject("acme-corp", "warehouse", "cam_1")  # Camera-specific
        "org.acme-corp.zone.warehouse.camera.cam_1.alarm"
    """
    if camera_id and zone_slug:
        return f"org.{org_slug}.zone.{zone_slug}.camera.{camera_id}.alarm"
    else:
        # Org-wide alarm subject
        return f"org.{org_slug}.events.alarm"
