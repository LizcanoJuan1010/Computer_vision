import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, Text, DECIMAL, func, Table, Column, text, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# PostgreSQL ENUMs (must match database schema)
import enum

class EventSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

class EventStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"

# Association Table for Role <-> Permissions
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_system_role: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))

    permissions: Mapped[List["Permission"]] = relationship(secondary=role_permissions, back_populates="roles")
    users: Mapped[List["User"]] = relationship(back_populates="role")

class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    roles: Mapped[List["Role"]] = relationship(secondary=role_permissions, back_populates="permissions")

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    role: Mapped[Optional["Role"]] = relationship(back_populates="users")

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_managed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    config: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zones: Mapped[List["OrgZone"]] = relationship(back_populates="organization", cascade="all, delete-orphan")

class OrgZone(Base):
    __tablename__ = "org_zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    location_description: Mapped[Optional[str]] = mapped_column(Text)
    geo_bounds: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization: Mapped["Organization"] = relationship(back_populates="zones")
    cameras: Mapped[List["Camera"]] = relationship(back_populates="zone", cascade="all, delete-orphan")

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rtsp_url: Mapped[str] = mapped_column(Text, nullable=False)
    location_name: Mapped[Optional[str]] = mapped_column(String(100))
    # geo_location is POINT type - omitted for now (can add custom type if needed)

    # Multi-tenancy: Link to zone
    zone_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org_zones.id", ondelete="CASCADE"),
        nullable=True
    )

    meta_info: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    zone: Mapped[Optional["OrgZone"]] = relationship(back_populates="cameras")
    configs: Mapped[List["CameraAIConfig"]] = relationship(back_populates="camera", cascade="all, delete-orphan")
    events: Mapped[List["Event"]] = relationship(back_populates="camera")

class CameraAIConfig(Base):
    __tablename__ = "camera_ai_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    default_severity: Mapped[str] = mapped_column(
        Enum(EventSeverity, name="event_severity_enum", create_type=False),
        server_default=text("'MEDIUM'::event_severity_enum")
    )
    confidence_threshold: Mapped[float] = mapped_column(DECIMAL(4,3), server_default=text("0.700"))
    debounce_seconds: Mapped[int] = mapped_column(Integer, server_default=text("60"))
    roi_polygon: Mapped[Optional[list]] = mapped_column(JSONB)
    active_schedule: Mapped[Optional[dict]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    camera: Mapped["Camera"] = relationship(back_populates="configs")

class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    camera_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"))
    config_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("camera_ai_configs.id"))
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    track_id: Mapped[Optional[str]] = mapped_column(String(100))
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(4,3))
    snapshot_path: Mapped[Optional[str]] = mapped_column(Text)
    video_clip_path: Mapped[Optional[str]] = mapped_column(Text)
    bbox: Mapped[Optional[list]] = mapped_column(JSONB)
    severity: Mapped[str] = mapped_column(
        Enum(EventSeverity, name="event_severity_enum", create_type=False),
        server_default=text("'MEDIUM'::event_severity_enum")
    )
    status: Mapped[str] = mapped_column(
        Enum(EventStatus, name="event_status_enum", create_type=False),
        server_default=text("'PENDING'::event_status_enum")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    camera: Mapped[Optional["Camera"]] = relationship(back_populates="events")
    actions: Mapped[List["EventAction"]] = relationship(back_populates="event", cascade="all, delete-orphan")

class EventAction(Base):
    __tablename__ = "event_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    previous_status: Mapped[Optional[str]] = mapped_column(
        Enum(EventStatus, name="event_status_enum", create_type=False)
    )
    new_status: Mapped[Optional[str]] = mapped_column(
        Enum(EventStatus, name="event_status_enum", create_type=False)
    )
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped["Event"] = relationship(back_populates="actions")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    module: Mapped[Optional[str]] = mapped_column(String(50))
    action: Mapped[Optional[str]] = mapped_column(String(50))
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    details: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class FaceCategory(str, enum.Enum):
    KNOWN = "KNOWN"
    BLACKLIST = "BLACKLIST"
    UNKNOWN = "UNKNOWN"

class Face(Base):
    __tablename__ = "faces"

    # Note: faces table uses SERIAL (Integer) for compatibility with pgvector
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    # Multi-tenancy support
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True
    )

    # Face classification (KNOWN, BLACKLIST, UNKNOWN)
    category: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'KNOWN'")
    )

    # Additional metadata
    meta_info: Mapped[Optional[dict]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

    # Image storage path (for training purposes)
    image_path: Mapped[Optional[str]] = mapped_column(Text)

    # embedding is vector(512), mapped as custom type or ignored in basic ORM
    # We'll rely on raw SQL for inserting embedding, but ORM can read name/id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    organization: Mapped[Optional["Organization"]] = relationship("Organization")

class NotificationChannelType(str, enum.Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    WEBHOOK = "WEBHOOK"
    SLACK = "SLACK"
    TELEGRAM = "TELEGRAM"
    WHATSAPP = "WHATSAPP"

class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)  # EMAIL, SMS, WEBHOOK, etc.
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)  # Channel-specific configuration
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization: Mapped["Organization"] = relationship("Organization")
    rules: Mapped[List["NotificationRule"]] = relationship(back_populates="channel")

class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_channels.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Trigger conditions
    event_types: Mapped[Optional[list]] = mapped_column(JSONB)  # ['intrusion', 'loitering', etc.]
    severities: Mapped[Optional[list]] = mapped_column(JSONB)  # ['CRITICAL', 'HIGH']
    camera_ids: Mapped[Optional[list]] = mapped_column(JSONB)  # Specific cameras (UUIDs as strings)
    zone_ids: Mapped[Optional[list]] = mapped_column(JSONB)  # Specific zones (UUIDs as strings)

    # Schedule
    active_schedule: Mapped[Optional[dict]] = mapped_column(JSONB)  # When rule is active

    # Rate limiting
    cooldown_minutes: Mapped[int] = mapped_column(Integer, server_default=text("5"))  # Min time between notifications

    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    organization: Mapped["Organization"] = relationship("Organization")
    channel: Mapped["NotificationChannel"] = relationship(back_populates="rules")

class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification_rules.id", ondelete="CASCADE")
    )
    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="SET NULL")
    )
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)  # email, phone, webhook URL
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # SENT, FAILED, PENDING
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    rule: Mapped["NotificationRule"] = relationship("NotificationRule")
    event: Mapped[Optional["Event"]] = relationship("Event")
