"""The agent layer as the API exposes it: /agent/draft-listing, background triggers,
the per-user daily budget guard, and graceful degradation when the agent is down."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.orchestrator import AgentBudgetExceeded, AgentResult, AgentUnavailable
from agent.orchestrator import AgentTask as OrchestratorTask
from app.models import AgentRun, AgentRunStatus, Listing, Notification, WishlistItem
from app.services import agent_service
from tests.conftest import TINY_PNG, ApiUser, create_listing

DRAFT = "/api/v1/agent/draft-listing"
LISTINGS = "/api/v1/listings"
CLAIMS = "/api/v1/claims"


@pytest.fixture
def agent_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the agent layer (the suite disables it by default)."""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "agent_daily_budget", 20)


def result(task: OrchestratorTask, data: dict[str, Any], **kwargs: Any) -> AgentResult:
    return AgentResult(task=task, data=data, summary=kwargs.pop("summary", "ok"), **kwargs)


def patch_agent_loop(
    monkeypatch: pytest.MonkeyPatch, task: OrchestratorTask, data: dict[str, Any]
) -> list[dict]:
    """Stub only the agentic loop, leaving the orchestrator's session and budget
    handling (which is where the guard lives) running for real."""
    calls: list[dict] = []

    async def _fake_run_agent(**kwargs: Any) -> AgentResult:
        calls.append(kwargs)
        return result(task, dict(data))

    monkeypatch.setattr(agent_service.orchestrator, "run_agent", _fake_run_agent)
    return calls


def patch_orchestrator(monkeypatch: pytest.MonkeyPatch, name: str, value: Any) -> list[dict]:
    """Replace one orchestrator entry point; returns a list recording its calls."""
    calls: list[dict] = []

    async def _fake(*args: Any, **kwargs: Any) -> Any:
        calls.append({"args": args, "kwargs": kwargs})
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(agent_service.orchestrator, name, _fake)
    return calls


# ------------------------------------------------------------- POST /agent/draft-listing


def test_draft_listing_returns_editable_fields(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    patch_orchestrator(
        monkeypatch,
        "process_new_listing_photo",
        result(
            OrchestratorTask.DRAFT_LISTING,
            {
                "title": "Ikea Malm desk",
                "description": "White laminate desk, light scuffing on top.",
                "category": "furniture",
                "condition": "good",
                "confidence": 0.78,
                "flagged": False,
                "flag_reason": None,
            },
            summary="Drafted from the photo.",
            tool_calls=[],
        ),
    )
    response = owner.client.post(
        DRAFT, files={"photo": ("desk.png", TINY_PNG, "image/png")}, headers=owner.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Ikea Malm desk"
    assert body["category"] == "furniture"
    assert body["condition"] == "good"
    assert body["confidence"] == 0.78
    assert body["flagged"] is False
    # The photo was stored once, under this user's draft prefix, for reuse on create.
    assert body["photo_key"].startswith(f"drafts/{owner.id}/")


def test_the_drafted_photo_can_be_adopted_without_re_uploading(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    patch_orchestrator(
        monkeypatch,
        "process_new_listing_photo",
        result(
            OrchestratorTask.DRAFT_LISTING,
            {
                "title": "Ikea Malm desk",
                "description": "White desk.",
                "category": "furniture",
                "condition": "good",
                "confidence": 0.8,
                "flagged": False,
                "flag_reason": None,
            },
        ),
    )
    drafted = owner.client.post(
        DRAFT, files={"photo": ("desk.png", TINY_PNG, "image/png")}, headers=owner.headers
    ).json()

    created = owner.client.post(
        LISTINGS,
        data={
            "title": drafted["title"],
            "description": drafted["description"],
            "category": drafted["category"],
            "condition": drafted["condition"],
            "pickup_area": "Guy-Concordia metro",
            "ai_generated": "true",
            "draft_photo_keys": drafted["photo_key"],
        },
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["ai_generated"] is True
    assert len(body["photos"]) == 1
    assert owner.client.get(body["photos"][0]).content == TINY_PNG


def test_draft_listing_surfaces_a_flagged_item_to_the_student(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    patch_orchestrator(
        monkeypatch,
        "process_new_listing_photo",
        result(
            OrchestratorTask.DRAFT_LISTING,
            {
                "title": "Bottle of vodka",
                "description": "Unopened 750ml bottle.",
                "category": "other",
                "condition": "like_new",
                "confidence": 0.95,
                "flagged": True,
                "flag_reason": "Alcohol cannot be given away on FreeCycle.",
            },
        ),
    )
    body = owner.client.post(
        DRAFT, files={"photo": ("x.png", TINY_PNG, "image/png")}, headers=owner.headers
    ).json()
    assert body["flagged"] is True
    assert "Alcohol" in body["flag_reason"]


def test_draft_listing_requires_authentication(client: TestClient) -> None:
    response = client.post(DRAFT, files={"photo": ("x.png", TINY_PNG, "image/png")})
    assert response.status_code == 401


def test_draft_listing_rejects_a_non_image(agent_on, owner: ApiUser) -> None:
    response = owner.client.post(
        DRAFT, files={"photo": ("x.pdf", b"%PDF-1.4", "application/pdf")}, headers=owner.headers
    )
    assert response.status_code == 422


# ------------------------------------------------------------- graceful degradation


def test_draft_listing_is_503_when_the_agent_layer_is_unconfigured(owner: ApiUser) -> None:
    """No ANTHROPIC_API_KEY / feature off: a clear 503, not a 500."""
    response = owner.client.post(
        DRAFT, files={"photo": ("x.png", TINY_PNG, "image/png")}, headers=owner.headers
    )
    assert response.status_code == 503
    assert "fill the form in manually" in response.json()["detail"]


def test_draft_listing_is_503_when_the_agent_layer_is_down(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    patch_orchestrator(
        monkeypatch, "process_new_listing_photo", AgentUnavailable("MCP server unreachable")
    )
    response = owner.client.post(
        DRAFT, files={"photo": ("x.png", TINY_PNG, "image/png")}, headers=owner.headers
    )
    assert response.status_code == 503


def test_listing_creation_still_works_with_the_agent_layer_down(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    """The headline degradation requirement: manual listing creation is unaffected."""
    patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("down"))
    patch_orchestrator(monkeypatch, "run_matching", AgentUnavailable("down"))

    body = create_listing(owner, title="Manual desk")
    assert body["status"] == "available"
    # A listing is never hidden because a check could not be run.
    assert body["flagged"] is False
    assert owner.client.get(f"{LISTINGS}/{body['id']}").status_code == 200


def test_listing_creation_survives_a_crashing_background_task(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    patch_orchestrator(monkeypatch, "moderate_listing", RuntimeError("unexpected explosion"))
    body = create_listing(owner, title="Still created")
    assert body["id"]
    assert owner.client.get(f"{LISTINGS}/{body['id']}").status_code == 200


def test_accepting_a_claim_still_works_without_a_drafted_message(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, claimer: ApiUser
) -> None:
    patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("down"))
    patch_orchestrator(monkeypatch, "run_matching", AgentUnavailable("down"))
    patch_orchestrator(monkeypatch, "draft_pickup_message", AgentUnavailable("down"))

    listing = create_listing(owner)
    claim = claimer.client.post(
        f"{LISTINGS}/{listing['id']}/claims", json={"message": "hi"}, headers=claimer.headers
    ).json()
    response = owner.client.patch(
        f"{CLAIMS}/{claim['id']}", json={"action": "accept"}, headers=owner.headers
    )
    assert response.status_code == 200
    pickup = response.json()["pickup"]
    assert pickup["drafted_message"] is None      # nothing to copy
    assert pickup["owner_email"] == owner.email   # the contact channel still works


def test_accepting_a_claim_includes_the_drafted_message(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, claimer: ApiUser
) -> None:
    patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("skip"))
    patch_orchestrator(monkeypatch, "run_matching", AgentUnavailable("skip"))
    drafted = "Hi Claimer Chris, the desk is yours! I'm usually near Guy-Concordia metro..."
    calls = patch_orchestrator(
        monkeypatch,
        "draft_pickup_message",
        result(OrchestratorTask.DRAFT_PICKUP_MESSAGE, {"message": drafted}),
    )

    listing = create_listing(owner)
    claim = claimer.client.post(
        f"{LISTINGS}/{listing['id']}/claims", json={"message": "hi"}, headers=claimer.headers
    ).json()
    response = owner.client.patch(
        f"{CLAIMS}/{claim['id']}", json={"action": "accept"}, headers=owner.headers
    )
    body = response.json()
    assert body["pickup"]["drafted_message"] == drafted
    assert calls[0]["args"] == (listing["id"], claim["id"])


def test_declining_does_not_call_the_agent(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, claimer: ApiUser
) -> None:
    patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("skip"))
    patch_orchestrator(monkeypatch, "run_matching", AgentUnavailable("skip"))
    calls = patch_orchestrator(
        monkeypatch, "draft_pickup_message",
        result(OrchestratorTask.DRAFT_PICKUP_MESSAGE, {"message": "x"}),
    )
    listing = create_listing(owner)
    claim = claimer.client.post(
        f"{LISTINGS}/{listing['id']}/claims", json={"message": "hi"}, headers=claimer.headers
    ).json()
    owner.client.patch(f"{CLAIMS}/{claim['id']}", json={"action": "decline"},
                       headers=owner.headers)
    assert calls == []


def test_nothing_is_triggered_when_the_agent_layer_is_disabled(
    monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    calls = patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("x"))
    create_listing(owner)
    assert calls == []  # agent_configured is False, so no run is attempted


# ------------------------------------------------------------- background triggers


def test_a_flagged_listing_becomes_invisible_and_shows_the_owner_a_notice(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, client: TestClient
) -> None:
    patch_orchestrator(
        monkeypatch,
        "moderate_listing",
        result(
            OrchestratorTask.MODERATE_LISTING,
            {"flagged": True, "flag_reason": "Alcohol cannot be given away here."},
        ),
    )
    matching = patch_orchestrator(monkeypatch, "run_matching", AgentUnavailable("never called"))

    listing = create_listing(owner, title="Free vodka", description="Unopened bottle")

    # Invisible to everyone else...
    assert client.get(f"{LISTINGS}/{listing['id']}").status_code == 404
    assert client.get(LISTINGS).json()["total"] == 0
    # ...but the owner sees it with the reason.
    owner_view = owner.client.get(f"{LISTINGS}/{listing['id']}", headers=owner.headers).json()
    assert owner_view["flagged"] is True
    assert owner_view["flag_reason"] == "Alcohol cannot be given away here."
    # A flagged listing must never generate wishlist notifications.
    assert matching == []


def test_a_clean_listing_runs_matching_and_creates_notifications(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, claimer: ApiUser, db
) -> None:
    db.add(WishlistItem(user_id=claimer.id, keywords="table for studying", category="furniture"))
    db.commit()
    item_id = db.query(WishlistItem).one().id

    patch_orchestrator(
        monkeypatch,
        "moderate_listing",
        result(OrchestratorTask.MODERATE_LISTING, {"flagged": False, "flag_reason": None}),
    )
    patch_orchestrator(
        monkeypatch,
        "run_matching",
        result(
            OrchestratorTask.RUN_MATCHING,
            {
                "flagged": False,
                "matches": [
                    {
                        "user_id": claimer.id,
                        "wishlist_item_id": item_id,
                        "score": 0.92,
                        "rationale": "'table for studying' is this study desk.",
                    }
                ],
            },
        ),
    )

    listing = create_listing(owner, title="Ikea study desk")

    bell = claimer.client.get("/api/v1/notifications", headers=claimer.headers).json()
    assert bell["unread_count"] == 1
    notification = bell["items"][0]
    assert notification["type"] == "wishlist_match"
    assert notification["payload"]["listing_id"] == listing["id"]
    assert notification["payload"]["wishlist_item_id"] == item_id
    assert notification["payload"]["score"] == 0.92
    assert "table for studying" in notification["payload"]["rationale"]


@pytest.mark.parametrize(
    "match_override",
    [
        pytest.param({"wishlist_item_id": 987654}, id="wishlist item does not exist"),
        pytest.param({"score": 0.2}, id="score below threshold"),
        pytest.param({"user_id": None}, id="malformed user id"),
        pytest.param({}, id="wishlist item belongs to another user"),
    ],
)
def test_bad_matches_never_become_notifications(
    agent_on,
    monkeypatch: pytest.MonkeyPatch,
    owner: ApiUser,
    claimer: ApiUser,
    db,
    match_override: dict[str, Any],
) -> None:
    """A hallucinated or weak match must not notify a student."""
    from tests.conftest import register_user

    third = register_user(db_client := claimer.client, email="third-party@concordia.ca")
    db.add(WishlistItem(user_id=third.id, keywords="a study table"))
    db.commit()
    item_id = db.query(WishlistItem).one().id

    match: dict[str, Any] = {
        "user_id": claimer.id,   # wrong owner for this wishlist item
        "wishlist_item_id": item_id,
        "score": 0.9,
        "rationale": "r",
    } | match_override

    patch_orchestrator(
        monkeypatch,
        "moderate_listing",
        result(OrchestratorTask.MODERATE_LISTING, {"flagged": False, "flag_reason": None}),
    )
    patch_orchestrator(
        monkeypatch,
        "run_matching",
        result(OrchestratorTask.RUN_MATCHING, {"flagged": False, "matches": [match]}),
    )

    create_listing(owner, title="Ikea study desk")
    assert db.query(Notification).count() == 0


def test_an_owner_is_never_notified_about_their_own_listing(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, db
) -> None:
    db.add(WishlistItem(user_id=owner.id, keywords="a study desk"))
    db.commit()
    item_id = db.query(WishlistItem).one().id

    patch_orchestrator(
        monkeypatch, "moderate_listing",
        result(OrchestratorTask.MODERATE_LISTING, {"flagged": False, "flag_reason": None}),
    )
    patch_orchestrator(
        monkeypatch,
        "run_matching",
        result(
            OrchestratorTask.RUN_MATCHING,
            {"flagged": False, "matches": [
                {"user_id": owner.id, "wishlist_item_id": item_id, "score": 0.99,
                 "rationale": "your own listing"}
            ]},
        ),
    )
    create_listing(owner, title="Ikea study desk")
    assert db.query(Notification).count() == 0


def test_moderation_failure_does_not_block_matching_from_being_attempted(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("down"))
    matching = patch_orchestrator(
        monkeypatch, "run_matching",
        result(OrchestratorTask.RUN_MATCHING, {"flagged": False, "matches": []}),
    )
    create_listing(owner)
    assert len(matching) == 1  # an unavailable check is 'not flagged', so matching proceeds


# ------------------------------------------------------------- budget guard


def test_the_budget_guard_counts_runs_and_then_refuses(db, owner: ApiUser) -> None:
    guard = agent_service.DbBudgetGuard(db, daily_budget=2)
    task = OrchestratorTask.MODERATE_LISTING

    guard.check(owner.id, task)
    guard.record(owner.id, task, result(task, {}, input_tokens=100, output_tokens=20), None)
    guard.check(owner.id, task)
    guard.record(owner.id, task, result(task, {}), None)

    with pytest.raises(AgentBudgetExceeded, match="2/2"):
        guard.check(owner.id, task)


def test_the_budget_is_per_user(db, owner: ApiUser, claimer: ApiUser) -> None:
    guard = agent_service.DbBudgetGuard(db, daily_budget=1)
    task = OrchestratorTask.RUN_MATCHING
    guard.record(owner.id, task, result(task, {}), None)

    with pytest.raises(AgentBudgetExceeded):
        guard.check(owner.id, task)
    guard.check(claimer.id, task)  # a different student is unaffected


def test_a_budget_refusal_does_not_itself_consume_budget(db, owner: ApiUser) -> None:
    guard = agent_service.DbBudgetGuard(db, daily_budget=1)
    task = OrchestratorTask.RUN_MATCHING
    guard.record(owner.id, task, result(task, {}), None)

    for _ in range(3):
        with pytest.raises(AgentBudgetExceeded):
            guard.check(owner.id, task)

    rows = db.query(AgentRun).filter(AgentRun.user_id == owner.id).all()
    counted = [row for row in rows if row.status != AgentRunStatus.BUDGET_EXCEEDED]
    assert len(counted) == 1
    assert len(rows) == 4  # the refusals are recorded, but not counted


def test_a_zero_budget_disables_the_agent(db, owner: ApiUser) -> None:
    guard = agent_service.DbBudgetGuard(db, daily_budget=0)
    with pytest.raises(AgentBudgetExceeded, match="disabled"):
        guard.check(owner.id, OrchestratorTask.RUN_MATCHING)


def test_runs_are_recorded_with_their_tokens_and_latency(db, owner: ApiUser) -> None:
    guard = agent_service.DbBudgetGuard(db)
    task = OrchestratorTask.DRAFT_LISTING
    from agent.orchestrator import ToolCallLog

    guard.record(
        owner.id,
        task,
        result(
            task,
            {},
            input_tokens=1234,
            output_tokens=567,
            latency_ms=2500.4,
            tool_calls=[
                ToolCallLog("flag_prohibited", {}, 12.0, True),
                ToolCallLog("match_wishlist", {}, 34.0, True),
            ],
        ),
        None,
    )
    row = db.query(AgentRun).one()
    assert row.status == AgentRunStatus.SUCCEEDED
    assert row.task.value == "draft_listing"
    assert (row.input_tokens, row.output_tokens) == (1234, 567)
    assert row.latency_ms == 2500
    assert row.tool_calls == 2
    assert row.error is None


def test_a_failed_run_is_recorded_with_its_error(db, owner: ApiUser) -> None:
    guard = agent_service.DbBudgetGuard(db)
    guard.record(owner.id, OrchestratorTask.RUN_MATCHING, None, "MCP server unreachable")
    row = db.query(AgentRun).one()
    assert row.status == AgentRunStatus.FAILED
    assert row.error == "MCP server unreachable"


def test_draft_listing_returns_429_when_over_budget(
    agent_on, live_mcp, monkeypatch: pytest.MonkeyPatch, owner: ApiUser
) -> None:
    """Runs through the real orchestrator session, so the guard is genuinely applied."""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_daily_budget", 1)
    patch_agent_loop(
        monkeypatch,
        OrchestratorTask.DRAFT_LISTING,
        {
            "title": "Desk", "description": "d", "category": "furniture",
            "condition": "good", "confidence": 0.8, "flagged": False, "flag_reason": None,
        },
    )
    files = {"photo": ("x.png", TINY_PNG, "image/png")}
    first = owner.client.post(DRAFT, files=files, headers=owner.headers)
    assert first.status_code == 200

    second = owner.client.post(
        DRAFT, files={"photo": ("y.png", TINY_PNG, "image/png")}, headers=owner.headers
    )
    assert second.status_code == 429
    assert "budget" in second.json()["detail"].lower()


def test_the_guard_runs_before_the_agent_does(
    agent_on, live_mcp, monkeypatch: pytest.MonkeyPatch, db, owner: ApiUser
) -> None:
    """Over budget means no agent loop runs at all, not one whose result is discarded."""
    from app.config import settings

    monkeypatch.setattr(settings, "agent_daily_budget", 1)
    agent_service.DbBudgetGuard(db, daily_budget=1).record(
        owner.id, OrchestratorTask.DRAFT_LISTING, result(OrchestratorTask.DRAFT_LISTING, {}), None
    )

    calls = patch_agent_loop(monkeypatch, OrchestratorTask.DRAFT_LISTING, {})
    response = owner.client.post(
        DRAFT, files={"photo": ("x.png", TINY_PNG, "image/png")}, headers=owner.headers
    )
    assert response.status_code == 429
    assert calls == []


def test_the_drafted_message_survives_a_reload(
    agent_on, monkeypatch: pytest.MonkeyPatch, owner: ApiUser, claimer: ApiUser
) -> None:
    """The draft is persisted on the claim, so it is not lost and not re-billed."""
    patch_orchestrator(monkeypatch, "moderate_listing", AgentUnavailable("skip"))
    patch_orchestrator(monkeypatch, "run_matching", AgentUnavailable("skip"))
    drafted = "Hi Claimer Chris, the desk is yours - I'm near Guy-Concordia most afternoons."
    calls = patch_orchestrator(
        monkeypatch,
        "draft_pickup_message",
        result(OrchestratorTask.DRAFT_PICKUP_MESSAGE, {"message": drafted}),
    )

    listing = create_listing(owner)
    claim = claimer.client.post(
        f"{LISTINGS}/{listing['id']}/claims", json={"message": "hi"}, headers=claimer.headers
    ).json()
    owner.client.patch(f"{CLAIMS}/{claim['id']}", json={"action": "accept"},
                       headers=owner.headers)

    # Both parties still see it on a later request...
    mine = claimer.client.get(f"{CLAIMS}/mine", headers=claimer.headers).json()
    assert mine[0]["pickup"]["drafted_message"] == drafted
    queue = owner.client.get(f"{LISTINGS}/{listing['id']}/claims", headers=owner.headers)
    assert queue.status_code == 200

    # ...and completing the claim does not draft a second time.
    completed = owner.client.patch(
        f"{CLAIMS}/{claim['id']}", json={"action": "complete"}, headers=owner.headers
    ).json()
    assert completed["pickup"]["drafted_message"] == drafted
    assert len(calls) == 1
