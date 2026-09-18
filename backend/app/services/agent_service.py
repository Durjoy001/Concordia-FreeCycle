"""The backend's bridge to the agent layer.

Everything AI passes through here, and every function degrades: if the agent layer
is misconfigured, over budget, or simply down, the caller gets None (or a
ServiceError for the interactive endpoint) and the manual flow carries on.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from agent import orchestrator
from agent.orchestrator import AgentBudgetExceeded, AgentResult, AgentUnavailable
from agent.orchestrator import AgentTask as OrchestratorTask
from app.config import settings
from app.database import session_scope
from app.models import AgentRun, AgentRunStatus, AgentTask, Listing, WishlistItem
from app.services import listing_service, notification_service
from app.services.exceptions import AgentUnavailable as AgentUnavailableError
from app.services.exceptions import BudgetExceeded
from app.services.storage import get_storage

logger = logging.getLogger("freecycle.agent.bridge")


def _task(task: OrchestratorTask) -> AgentTask:
    """Orchestrator task -> DB enum (the two enums are kept in step deliberately)."""
    return AgentTask(task.value)


class DbBudgetGuard:
    """Per-user daily budget, counted from the agent_runs table.

    The orchestrator defines the BudgetGuard protocol but owns no database; the
    counting and the audit rows live here, next to the models.
    """

    def __init__(self, db: Session, daily_budget: int | None = None) -> None:
        self._db = db
        self._budget = settings.agent_daily_budget if daily_budget is None else daily_budget

    def _runs_today(self, user_id: int) -> int:
        since = datetime.now(timezone.utc) - timedelta(days=1)
        return int(
            self._db.execute(
                sa.select(sa.func.count(AgentRun.id)).where(
                    AgentRun.user_id == user_id,
                    AgentRun.created_at >= since,
                    # A run rejected by the budget guard does not consume budget itself.
                    AgentRun.status != AgentRunStatus.BUDGET_EXCEEDED,
                )
            ).scalar_one()
        )

    def check(self, user_id: int, task: OrchestratorTask) -> None:
        if self._budget <= 0:
            raise AgentBudgetExceeded("The AI assistant is disabled.")
        used = self._runs_today(user_id)
        if used >= self._budget:
            self._write(
                user_id,
                task,
                status=AgentRunStatus.BUDGET_EXCEEDED,
                error=f"{used}/{self._budget} runs used in the last 24h",
            )
            raise AgentBudgetExceeded(
                f"Daily AI assistant budget reached ({used}/{self._budget}). Try again tomorrow."
            )

    def record(
        self,
        user_id: int,
        task: OrchestratorTask,
        result: AgentResult | None,
        error: str | None,
    ) -> None:
        if result is not None:
            self._write(
                user_id,
                task,
                status=AgentRunStatus.SUCCEEDED,
                tool_calls=result.tool_call_count,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=int(result.latency_ms),
            )
        else:
            self._write(user_id, task, status=AgentRunStatus.FAILED, error=error)

    def _write(
        self,
        user_id: int,
        task: OrchestratorTask,
        *,
        status: AgentRunStatus,
        tool_calls: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
        listing_id: int | None = None,
    ) -> None:
        run = AgentRun(
            user_id=user_id,
            task=_task(task),
            status=status,
            listing_id=listing_id,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            error=(error[:2000] if error else None),
        )
        self._db.add(run)
        self._db.commit()


def _run(coro: Any) -> Any:
    """Drive an async orchestrator call from sync code (routers, BackgroundTasks)."""
    return asyncio.run(coro)


# --------------------------------------------------------------- interactive: drafting


def draft_listing_from_photo(db: Session, *, user_id: int, photo_key: str) -> dict[str, Any]:
    """POST /agent/draft-listing. Raises a ServiceError the router can return."""
    if not settings.agent_configured:
        raise AgentUnavailableError()

    guard = DbBudgetGuard(db)
    try:
        result: AgentResult = _run(
            orchestrator.process_new_listing_photo(photo_key, user_id=user_id, guard=guard)
        )
    except AgentBudgetExceeded as exc:
        raise BudgetExceeded(str(exc)) from exc
    except AgentUnavailable as exc:
        logger.warning("draft-listing degraded: %s", exc)
        raise AgentUnavailableError() from exc

    data = dict(result.data)
    data["photo_key"] = photo_key
    data["tools_used"] = result.tools_used()
    return data


# --------------------------------------------------------------- background: moderation


def moderate_and_match(listing_id: int, owner_id: int) -> None:
    """BackgroundTask after listing creation: moderate, then match if clean.

    Owns its own session because the request's session is closed by the time this
    runs. Never raises - a failure here must not affect the created listing.
    """
    if not settings.agent_configured:
        logger.info("agent layer disabled; skipping moderation and matching")
        return

    db = session_scope()
    try:
        listing = db.get(Listing, listing_id)
        if listing is None:
            return
        photo_key = (listing.photos or [None])[0]
        title, description = listing.title, listing.description
        guard = DbBudgetGuard(db)

        flagged = _moderate(
            db, guard, listing_id=listing_id, owner_id=owner_id,
            title=title, description=description, photo_key=photo_key,
        )
        if flagged:
            # A flagged listing is invisible, so notifying anyone about it would be wrong.
            logger.info("listing %s flagged; skipping wishlist matching", listing_id)
            return
        _match(
            db, guard, listing_id=listing_id, owner_id=owner_id,
            title=title, description=description, photo_key=photo_key,
        )
    except Exception:  # noqa: BLE001 - background task of last resort
        logger.exception("background agent work failed for listing %s", listing_id)
    finally:
        db.close()


def _moderate(
    db: Session,
    guard: DbBudgetGuard,
    *,
    listing_id: int,
    owner_id: int,
    title: str,
    description: str,
    photo_key: str | None,
) -> bool:
    """Returns True when the listing was flagged. Degrades to 'not flagged'."""
    try:
        result = _run(
            orchestrator.moderate_listing(
                listing_id,
                title=title,
                description=description,
                photo_path=photo_key,
                user_id=owner_id,
                guard=guard,
            )
        )
    except (AgentUnavailable, AgentBudgetExceeded) as exc:
        # Never hide a listing because a check could not be run.
        logger.warning("moderation unavailable for listing %s: %s", listing_id, exc)
        return False

    flagged = bool(result.data.get("flagged"))
    reason = result.data.get("flag_reason") if flagged else None
    listing_service.apply_moderation(
        db, listing_id=listing_id, flagged=flagged, reason=reason or (result.summary if flagged else None)
    )
    return flagged


def _match(
    db: Session,
    guard: DbBudgetGuard,
    *,
    listing_id: int,
    owner_id: int,
    title: str,
    description: str,
    photo_key: str | None,
) -> None:
    """Turn the matching agent's answer into notification rows."""
    try:
        result = _run(
            orchestrator.run_matching(
                listing_id,
                title=title,
                description=description,
                photo_path=photo_key,
                user_id=owner_id,
                guard=guard,
            )
        )
    except (AgentUnavailable, AgentBudgetExceeded) as exc:
        logger.warning("matching unavailable for listing %s: %s", listing_id, exc)
        return

    if result.data.get("flagged"):
        return

    listing = db.get(Listing, listing_id)
    if listing is None:
        return

    created = 0
    for match in result.data.get("matches", []):
        if _notify_match(db, listing=listing, owner_id=owner_id, match=match):
            created += 1
    logger.info(
        "listing %s matching produced %s notification(s) from %s candidate match(es)",
        listing_id,
        created,
        len(result.data.get("matches", [])),
    )


def _notify_match(
    db: Session, *, listing: Listing, owner_id: int, match: dict[str, Any]
) -> bool:
    """Validate one match against the database before it becomes a notification."""
    try:
        user_id = int(match["user_id"])
        item_id = int(match["wishlist_item_id"])
        score = float(match["score"])
    except (KeyError, TypeError, ValueError):
        logger.warning("discarding malformed match %r", match)
        return False

    if score < settings.match_score_threshold:
        return False
    if user_id == owner_id:
        return False

    item = db.get(WishlistItem, item_id)
    # The wishlist entry must exist and belong to the user the agent named - otherwise
    # the notification would go to the wrong student.
    if item is None or item.user_id != user_id:
        logger.warning("discarding match for unknown wishlist item %s/user %s", item_id, user_id)
        return False

    notification_service.notify_wishlist_match(
        db,
        user_id=user_id,
        listing=listing,
        wishlist_item_id=item_id,
        score=score,
        rationale=str(match.get("rationale") or ""),
    )
    return True


# --------------------------------------------------------------- pickup coordination


def draft_pickup_message(db: Session, *, listing_id: int, claim_id: int, user_id: int) -> str | None:
    """Best-effort pickup message. None means 'no draft', never an error."""
    if not settings.agent_configured:
        return None
    guard = DbBudgetGuard(db)
    try:
        result = _run(
            orchestrator.draft_pickup_message(
                listing_id, claim_id, user_id=user_id, guard=guard
            )
        )
    except (AgentUnavailable, AgentBudgetExceeded) as exc:
        logger.warning("pickup draft unavailable for claim %s: %s", claim_id, exc)
        return None
    message = result.data.get("message")
    return str(message) if message else None


# --------------------------------------------------------------- draft photo staging


def stage_draft_photo(*, user_id: int, stream: Any, content_type: str | None) -> str:
    """Store an uploaded photo under the user's draft prefix and return its key."""
    return get_storage().save(stream, prefix=f"drafts/{user_id}", content_type=content_type)
