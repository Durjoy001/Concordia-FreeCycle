"""Persist the agent-drafted pickup message on the claim

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-18

The message was previously only present in the accept response, so it was lost on
reload. Storing it also prevents paying for a second draft of the same handover.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("drafted_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claims", "drafted_message")
