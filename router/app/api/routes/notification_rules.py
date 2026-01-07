"""
Notifications and Alerts CRUD API endpoints

NOTIFICATION CHANNELS:
  - GET    /api/v1/orgs/{org_slug}/notification-channels/
  - POST   /api/v1/orgs/{org_slug}/notification-channels/
  - GET    /api/v1/orgs/{org_slug}/notification-channels/{channel_id}
  - PUT    /api/v1/orgs/{org_slug}/notification-channels/{channel_id}
  - DELETE /api/v1/orgs/{org_slug}/notification-channels/{channel_id}
  - POST   /api/v1/orgs/{org_slug}/notification-channels/{channel_id}/test

NOTIFICATION RULES:
  - GET    /api/v1/orgs/{org_slug}/notification-rules/
  - POST   /api/v1/orgs/{org_slug}/notification-rules/
  - GET    /api/v1/orgs/{org_slug}/notification-rules/{rule_id}
  - PUT    /api/v1/orgs/{org_slug}/notification-rules/{rule_id}
  - DELETE /api/v1/orgs/{org_slug}/notification-rules/{rule_id}

NOTIFICATION LOGS:
  - GET    /api/v1/orgs/{org_slug}/notification-logs/
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from app.core.database import get_db
from app.models import NotificationChannel, NotificationRule, NotificationLog, Organization
from app.api.routes.schemas_extended import (
    NotificationChannelCreate,
    NotificationChannelUpdate,
    NotificationChannelResponse,
    NotificationRuleCreate,
    NotificationRuleUpdate,
    NotificationRuleResponse,
    NotificationLogResponse,
    NotificationTestRequest,
    NotificationTestResponse
)
from app.api.dependencies import get_organization_by_slug
from app.services.notification_sender import notification_sender

router = APIRouter()
logger = logging.getLogger("router.notification_rules")


# ============================================================================
# NOTIFICATION CHANNELS
# ============================================================================

@router.get("/orgs/{org_slug}/notification-channels/", response_model=List[NotificationChannelResponse])
async def list_notification_channels(
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db),
    channel_type: Optional[str] = None,
    include_inactive: bool = False
):
    """
    List all notification channels for an organization.

    Channels define HOW notifications are sent (email, SMS, webhook, etc.)
    """
    query = select(NotificationChannel).where(NotificationChannel.organization_id == org.id)

    if channel_type:
        valid_types = ['EMAIL', 'SMS', 'WEBHOOK', 'SLACK', 'TELEGRAM', 'WHATSAPP']
        if channel_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid channel_type")
        query = query.where(NotificationChannel.channel_type == channel_type)

    if not include_inactive:
        query = query.where(NotificationChannel.is_active == True)

    query = query.order_by(NotificationChannel.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/orgs/{org_slug}/notification-channels/", response_model=NotificationChannelResponse, status_code=201)
async def create_notification_channel(
    channel: NotificationChannelCreate,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Create a new notification channel."""
    valid_types = ['EMAIL', 'SMS', 'WEBHOOK', 'SLACK', 'TELEGRAM', 'WHATSAPP']
    if channel.channel_type not in valid_types:
        raise HTTPException(status_code=400, detail="Invalid channel_type")

    new_channel = NotificationChannel(organization_id=org.id, **channel.dict())
    db.add(new_channel)

    try:
        await db.commit()
        await db.refresh(new_channel)
        return new_channel
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orgs/{org_slug}/notification-channels/{channel_id}", response_model=NotificationChannelResponse)
async def get_notification_channel(
    channel_id: UUID,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific notification channel."""
    channel = await db.get(NotificationChannel, channel_id)
    if not channel or channel.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


@router.put("/orgs/{org_slug}/notification-channels/{channel_id}", response_model=NotificationChannelResponse)
async def update_notification_channel(
    channel_id: UUID,
    channel_update: NotificationChannelUpdate,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Update a notification channel."""
    channel = await db.get(NotificationChannel, channel_id)
    if not channel or channel.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Channel not found")

    update_data = channel_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(channel, field, value)

    try:
        await db.commit()
        await db.refresh(channel)
        return channel
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orgs/{org_slug}/notification-channels/{channel_id}", status_code=204)
async def delete_notification_channel(
    channel_id: UUID,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Delete a notification channel (soft delete)."""
    channel = await db.get(NotificationChannel, channel_id)
    if not channel or channel.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.is_active = False
    await db.commit()
    return None


@router.post("/orgs/{org_slug}/notification-channels/{channel_id}/test", response_model=NotificationTestResponse)
async def test_notification_channel(
    channel_id: UUID,
    test_request: NotificationTestRequest,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """
    Test a notification channel by sending a test message.

    Sends a real notification through the configured channel to verify it works.
    """
    channel = await db.get(NotificationChannel, channel_id)
    if not channel or channel.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Channel not found")

    if not channel.is_active:
        raise HTTPException(status_code=400, detail="Channel is not active")

    # Use test recipient from request or default from channel config
    recipient = test_request.recipient if hasattr(test_request, 'recipient') and test_request.recipient else channel.config.get("default_recipient", "test@example.com")

    # Prepare test message
    subject = "🧪 VIGIAS-IA Test Notification"
    message = f"""
This is a test notification from VIGIAS-IA.

Channel: {channel.name}
Type: {channel.channel_type}
Organization: {org.name}

If you received this, your notification channel is configured correctly! ✅

Timestamp: {datetime.now().isoformat()}
"""

    metadata = {
        "test": True,
        "channel_id": str(channel_id),
        "channel_name": channel.name,
        "organization": org.name
    }

    try:
        # Send notification using the notification sender service
        result = await notification_sender.send(
            channel_type=channel.channel_type,
            channel_config=channel.config,
            recipient=recipient,
            subject=subject,
            message=message,
            metadata=metadata
        )

        # Log the test notification
        log = NotificationLog(
            rule_id=None,  # No rule for test notifications
            event_id=None,
            channel_type=channel.channel_type,
            recipient=recipient,
            status=result["status"],
            error_message=result.get("error_message"),
            sent_at=result["sent_at"]
        )
        db.add(log)
        await db.commit()

        return {
            "success": result["status"] == "SENT",
            "channel_id": str(channel_id),
            "channel_type": channel.channel_type,
            "delivery_time_ms": result["delivery_time_ms"],
            "message": f"Test notification {'sent successfully' if result['status'] == 'SENT' else 'failed'} via {channel.channel_type}",
            "error": result.get("error_message")
        }

    except Exception as e:
        logger.error(f"Test notification failed for channel {channel_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send test notification: {str(e)}")


# ============================================================================
# NOTIFICATION RULES
# ============================================================================

@router.get("/orgs/{org_slug}/notification-rules/", response_model=List[NotificationRuleResponse])
async def list_notification_rules(
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = False
):
    """List all notification rules for an organization."""
    query = select(NotificationRule).where(NotificationRule.organization_id == org.id)

    if not include_inactive:
        query = query.where(NotificationRule.is_active == True)

    query = query.order_by(NotificationRule.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/orgs/{org_slug}/notification-rules/", response_model=NotificationRuleResponse, status_code=201)
async def create_notification_rule(
    rule: NotificationRuleCreate,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Create a new notification rule."""
    # Verify channel exists
    channel = await db.get(NotificationChannel, rule.channel_id)
    if not channel or channel.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Channel not found")

    new_rule = NotificationRule(organization_id=org.id, **rule.dict())
    db.add(new_rule)

    try:
        await db.commit()
        await db.refresh(new_rule)
        return new_rule
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orgs/{org_slug}/notification-rules/{rule_id}", response_model=NotificationRuleResponse)
async def get_notification_rule(
    rule_id: UUID,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Get details of a specific notification rule."""
    rule = await db.get(NotificationRule, rule_id)
    if not rule or rule.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/orgs/{org_slug}/notification-rules/{rule_id}", response_model=NotificationRuleResponse)
async def update_notification_rule(
    rule_id: UUID,
    rule_update: NotificationRuleUpdate,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Update a notification rule."""
    rule = await db.get(NotificationRule, rule_id)
    if not rule or rule.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = rule_update.dict(exclude_unset=True)

    # Validate channel_id if being updated
    if 'channel_id' in update_data:
        channel = await db.get(NotificationChannel, update_data['channel_id'])
        if not channel or channel.organization_id != org.id:
            raise HTTPException(status_code=400, detail="Invalid channel_id")

    for field, value in update_data.items():
        setattr(rule, field, value)

    try:
        await db.commit()
        await db.refresh(rule)
        return rule
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orgs/{org_slug}/notification-rules/{rule_id}", status_code=204)
async def delete_notification_rule(
    rule_id: UUID,
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db)
):
    """Delete a notification rule (soft delete)."""
    rule = await db.get(NotificationRule, rule_id)
    if not rule or rule.organization_id != org.id:
        raise HTTPException(status_code=404, detail="Rule not found")

    rule.is_active = False
    await db.commit()
    return None


# ============================================================================
# NOTIFICATION LOGS
# ============================================================================

@router.get("/orgs/{org_slug}/notification-logs/", response_model=List[NotificationLogResponse])
async def list_notification_logs(
    org: Organization = Depends(get_organization_by_slug),
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    channel_type: Optional[str] = None
):
    """List notification delivery logs for an organization."""
    query = (
        select(NotificationLog)
        .join(NotificationRule, NotificationLog.rule_id == NotificationRule.id)
        .where(NotificationRule.organization_id == org.id)
    )

    if status:
        query = query.where(NotificationLog.status == status)
    if channel_type:
        query = query.where(NotificationLog.channel_type == channel_type)

    query = query.order_by(NotificationLog.sent_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()
