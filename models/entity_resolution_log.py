import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class EntityResolutionLog(Base):
    __tablename__ = "entity_resolution_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_a_id: Mapped[str] = mapped_column(Text, nullable=False)
    record_b_id: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # person/company/address
    rule_applied: Mapped[str] = mapped_column(Text, nullable=False)
    merged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    merged_by: Mapped[str] = mapped_column(Text, nullable=False)  # etl job name

    __table_args__ = (
        Index("ix_er_log_entity_type", "entity_type"),
        Index("ix_er_log_record_a_id", "record_a_id"),
    )


class EntityResolutionConflict(Base):
    __tablename__ = "entity_resolution_conflicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_a: Mapped[dict] = mapped_column(JSON, nullable=False)
    record_b: Mapped[dict] = mapped_column(JSON, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    conflict_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # merged/kept_separate/escalated

    __table_args__ = (
        Index("ix_er_conflicts_entity_type", "entity_type"),
        Index("ix_er_conflicts_resolved_at", "resolved_at"),
    )
