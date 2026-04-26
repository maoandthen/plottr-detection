"""Entity resolution log and conflicts tables.

Revision ID: 002
Revises: 001
Create Date: 2026-04-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_resolution_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_a_id", sa.Text, nullable=False),
        sa.Column("record_b_id", sa.Text, nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("rule_applied", sa.Text, nullable=False),
        sa.Column("merged", sa.Boolean, nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("merged_by", sa.Text, nullable=False),
    )
    op.create_index("ix_er_log_entity_type", "entity_resolution_log", ["entity_type"])
    op.create_index("ix_er_log_record_a_id", "entity_resolution_log", ["record_a_id"])

    op.create_table(
        "entity_resolution_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("record_a", postgresql.JSON, nullable=False),
        sa.Column("record_b", postgresql.JSON, nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("conflict_reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text, nullable=True),
        sa.Column("resolution", sa.String(50), nullable=True),
    )
    op.create_index("ix_er_conflicts_entity_type", "entity_resolution_conflicts", ["entity_type"])
    op.create_index("ix_er_conflicts_resolved_at", "entity_resolution_conflicts", ["resolved_at"])


def downgrade() -> None:
    op.drop_table("entity_resolution_conflicts")
    op.drop_table("entity_resolution_log")
