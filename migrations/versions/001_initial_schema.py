"""Initial schema: titles, companies, officers, pscs, charities.

Revision ID: 001
Revises:
Create Date: 2026-04-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "titles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title_number", sa.String(20), nullable=False),
        sa.Column("tenure", sa.String(20), nullable=False),
        sa.Column("proprietor_name", sa.Text, nullable=False),
        sa.Column("proprietor_category", sa.String(100), nullable=False),
        sa.Column("company_registration", sa.String(20), nullable=True),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("postcode", sa.String(10), nullable=False),
        sa.Column("geom", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("price_paid", sa.Numeric(15, 2), nullable=True),
        sa.Column("date_registered", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_titles_title_number", "titles", ["title_number"])
    op.create_index("ix_titles_company_registration", "titles", ["company_registration"])
    op.create_index("ix_titles_postcode", "titles", ["postcode"])

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_number", sa.String(20), nullable=False),
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("company_status", sa.String(50), nullable=False),
        sa.Column("company_type", sa.String(100), nullable=False),
        sa.Column("incorporated_on", sa.Date, nullable=True),
        sa.Column("registered_address", sa.Text, nullable=True),
        sa.Column("postcode", sa.String(10), nullable=True),
        sa.Column("sic_codes", postgresql.ARRAY(sa.String(10)), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_companies_company_number", "companies", ["company_number"])
    op.create_index("ix_companies_postcode", "companies", ["postcode"])

    op.create_table(
        "officers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_number", sa.String(20), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("appointed_on", sa.Date, nullable=True),
        sa.Column("resigned_on", sa.Date, nullable=True),
        sa.Column("nationality", sa.String(100), nullable=True),
        sa.Column("country_of_residence", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_officers_company_number", "officers", ["company_number"])

    op.create_table(
        "pscs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_number", sa.String(20), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("nature_of_control", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("nationality", sa.String(100), nullable=True),
        sa.Column("country_of_residence", sa.String(100), nullable=True),
        sa.Column("notified_on", sa.Date, nullable=True),
        sa.Column("ceased_on", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pscs_company_number", "pscs", ["company_number"])

    op.create_table(
        "charities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("charity_number", sa.String(20), nullable=False),
        sa.Column("charity_name", sa.Text, nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("registration_date", sa.Date, nullable=True),
        sa.Column("removal_date", sa.Date, nullable=True),
        sa.Column("registered_address", sa.Text, nullable=True),
        sa.Column("postcode", sa.String(10), nullable=True),
        sa.Column("income_band", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_charities_charity_number", "charities", ["charity_number"])
    op.create_index("ix_charities_postcode", "charities", ["postcode"])


def downgrade() -> None:
    op.drop_table("charities")
    op.drop_table("pscs")
    op.drop_table("officers")
    op.drop_table("companies")
    op.drop_table("titles")
