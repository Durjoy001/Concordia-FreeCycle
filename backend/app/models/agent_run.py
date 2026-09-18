"""Audit trail for orchestrator invocations.

Not part of the original data model, but the per-user daily budget guard and the
observability story both need durable per-run rows; the structured log alone is
not queryable from the request path.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin, pg_enum
from .enums import AgentRunStatus, AgentTask


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (sa.Index("ix_agent_runs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task: Mapped[AgentTask] = mapped_column(pg_enum(AgentTask, "agent_task"), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        pg_enum(AgentRunStatus, "agent_run_status"), nullable=False
    )
    listing_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("listings.id", ondelete="SET NULL"), nullable=True
    )
    tool_calls: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AgentRun id={self.id} task={self.task} status={self.status}>"
