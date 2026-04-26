import uuid
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import Date, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class Title(Base):
    __tablename__ = "titles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    tenure: Mapped[str] = mapped_column(String(20), nullable=False)
    proprietor_name: Mapped[str] = mapped_column(Text, nullable=False)
    proprietor_category: Mapped[str] = mapped_column(String(100), nullable=False)
    company_registration: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    postcode: Mapped[str] = mapped_column(String(10), nullable=False)
    geom: Mapped[object | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    price_paid: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    date_registered: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_titles_company_registration", "company_registration"),
        Index("ix_titles_postcode", "postcode"),
    )
