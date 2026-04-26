import uuid
from datetime import date, datetime

from sqlalchemy import ARRAY, Date, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    company_name: Mapped[str] = mapped_column(Text, nullable=False)
    company_status: Mapped[str] = mapped_column(String(50), nullable=False)
    company_type: Mapped[str] = mapped_column(String(100), nullable=False)
    incorporated_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    registered_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    postcode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sic_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_companies_postcode", "postcode"),)
