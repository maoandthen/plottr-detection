import uuid
from datetime import date, datetime

from sqlalchemy import Date, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Charity(Base):
    __tablename__ = "charities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    charity_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    charity_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    registration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    removal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    registered_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    income_band: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_charities_postcode", "postcode"),)
