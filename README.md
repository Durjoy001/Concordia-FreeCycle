# Concordia FreeCycle

A giveaway board for Concordia students: list what you no longer need, claim what
you do. Everything on it is free.

What makes it more than a CRUD app is the **agentic AI core**. Four AI features —
drafting a listing from a photo, moderating prohibited items, matching new listings
to student wishlists, and drafting pickup messages — are *not* inline API calls in
route handlers. They are five tools on an **MCP server**, driven by an **agent
orchestrator** that gives Claude the tools and lets Claude decide which to call.

---

## Quick start

```bash
git clone <this repo> && cd Concordia-FreeCycle
cp .env.example .env          # then put a real ANTHROPIC_API_KEY in it
docker compose up             # builds and starts all four services
```

| Service | URL | Notes |
|---|---|---|
| Frontend | http://localhost:5173 | Vite dev server |
| API | http://localhost:8000 | OpenAPI docs at `/docs` |
| MCP server | http://localhost:8765/mcp | Streamable HTTP transport |
| PostgreSQL | localhost:5432 | `freecycle` / `freecycle` |

Migrations run automatically: the `api` container executes `alembic upgrade head`
before uvicorn starts.

**Without an `ANTHROPIC_API_KEY` the app still works end to end** — you just get no
AI. Listings, claims, wishlists and notifications all behave normally, and
`POST /agent/draft-listing` answers `503` with a "fill the form in manually"
message. That is deliberate; see [Graceful degradation](#graceful-degradation).

### Running it without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt -r agent/requirements.txt \
            -r mcp-server/requirements.txt

# 1. database
export DATABASE_URL="postgresql+psycopg://freecycle:freecycle@localhost:5432/freecycle"
(cd backend && alembic upgrade head)

# 2. MCP server  (stdio also works - set MCP_TRANSPORT=stdio and skip this)
(cd mcp-server && python server.py --transport http --port 8765)

# 3. API
(cd backend && uvicorn app.main:app --reload)

# 4. frontend
(cd frontend && npm install && npm run dev)
```

### Tests

```bash
(cd backend     && pytest)   # 171 tests: auth, listings, claims, wishlist,
                             # notifications, orchestrator, budget, degradation
(cd mcp-server  && pytest)   #  31 tests: the five MCP tools over real MCP protocol
(cd frontend    && npm run typecheck && npm run build)
```

No test makes a network call. The Anthropic client is always stubbed, the MCP server
runs in-process over the real MCP protocol, and the database is SQLite, so the whole
suite runs with no Postgres daemon and no API key.

---

## Architecture

```
                         ┌──────────────────────────────┐
  browser  ──────────────►  frontend  (React 18 + TS)   │
                         │  Vite · Tailwind · strict TS  │
                         └──────────────┬───────────────┘
                                        │  REST /api/v1  (JWT access + refresh)
                                        ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  backend   FastAPI + SQLAlchemy 2.x                                       │
│                                                                           │
│   routers/ ──► services/ ──► models/ ──► PostgreSQL                       │
│   (thin)       (all logic)               (Alembic migrations)              │
│                    │                                                      │
│                    │  agent_service.py  ← the ONLY door to the AI layer   │
│                    │    · DbBudgetGuard (agent_runs rows / user / day)     │
│                    │    · BackgroundTasks after listing creation           │
└────────────────────┼──────────────────────────────────────────────────────┘
                     │  async entry points
                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  agent/orchestrator.py        THE AGENTIC LOOP                            │
│                                                                           │
│   1. open MCP session, list_tools()                                       │
│   2. give Claude the task prompt + those tool schemas                     │
│   3. Claude decides which tools to call, and in what order                │
│   4. execute each tool_use against the MCP server, feed results back      │
│   5. repeat until Claude returns a schema-constrained final answer        │
│                                                                           │
│   retry w/ backoff · iteration cap · one JSON log line per tool call      │
└────────────────────┬──────────────────────────────────────────────────────┘
                     │  MCP  (streamable HTTP in compose, stdio for dev/tests)
                     ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  mcp-server/server.py     five tools, strict in/out JSON schemas          │
│                                                                           │
│   create_listing_from_photo   classify_item      flag_prohibited          │
│   match_wishlist              draft_coordination                          │
│        │                            │                                    │
│        │  own READ-ONLY DB engine ──┴──► PostgreSQL (SELECT only)         │
│        ▼                                                                  │
│   Claude API  (claude-sonnet-4-6, vision + structured outputs)            │
└───────────────────────────────────────────────────────────────────────────┘
```

Two properties this layout buys:

- **The backend never talks to Claude.** Search `backend/` for `anthropic` and the
  only hit is `agent_service.py` importing the orchestrator. No route handler
  constructs a prompt.
- **The MCP server never mutates.** It holds its own engine and three `SELECT`
  statements, and its `./uploads` mount in compose is `:ro`. A test greps the SQL
  for `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`.

---

## The agentic flow, feature by feature

Claude chooses the tools in every case below. The orchestrator executes what it
asks for; it does not hard-code a sequence.

### 1. Draft a listing from a photo — `process_new_listing_photo`

```
student uploads photo → POST /agent/draft-listing
  → orchestrator: "a student uploaded this photo, draft the form"
      → Claude calls create_listing_from_photo(photo_path)
            → MCP tool base64s the image → Claude vision + structured output
            → {title, description, category, condition, confidence}
      → Claude calls flag_prohibited(photo, title, description)
            → so a student is never handed a draft that would be hidden
      → Claude returns the fields + moderation verdict
  → response: editable fields, ✨ AI-drafted badge, confidence, photo_key
```

Nothing is created. The student edits and confirms; `POST /listings` then adopts
`photo_key` so the image is not uploaded twice, and sets `ai_generated=true`.

### 2. Moderation — `moderate_listing`

Runs as a `BackgroundTask` after every listing creation, manual or AI-drafted.
Claude calls `flag_prohibited` (weapons, alcohol, medications, perishables,
counterfeits, sale attempts) with the photo *and* the text, since the image can
contradict the title. A flagged listing becomes invisible to everyone but its owner,
who sees the reason as a notice on their own listing.

### 3. Wishlist matching — `run_matching`

```
listing created → BackgroundTask
  → Claude calls flag_prohibited        (a prohibited listing must notify nobody)
  → if clean, Claude calls match_wishlist(listing_id)
       → the MCP tool reads the listing + every OTHER student's wishlist itself
       → Claude scores semantic relevance: "study desk" ↔ "table for studying"
       → returns matches above MATCH_SCORE_THRESHOLD
  → backend turns each surviving match into a Notification row
```

Matching is semantic, not keyword: "kettle" satisfies "something to boil water",
while "desk lamp" does *not* satisfy "desk".

### 4. Pickup coordination — `draft_pickup_message`

When the owner accepts a claim, Claude calls `draft_coordination(listing_id,
claim_id)`; the tool reads both display names and the pickup area from the database
and writes the message. It is returned in the accept response **and stored on the
claim**, so both parties still have it after a reload and it is never re-drafted.
The prompt forbids inventing a date, time, room or street address.

### Trust boundaries

The agent's output is validated twice before it can affect a student:

1. **In the MCP tool** — `match_wishlist` intersects Claude's returned
   `(user_id, wishlist_item_id)` pairs against the candidates actually put in the
   prompt, then applies the score threshold.
2. **In the backend** — `_notify_match` re-checks against the database that each
   wishlist entry exists *and belongs to the user the agent named*, is above
   threshold, and is not the owner's own.

A hallucinated id would otherwise notify the wrong student. Both layers have tests.

### Observability

Every tool call emits one JSON line on the `freecycle.agent` logger, and every run
emits a summary:

```json
{"event":"agent_tool_call","task":"run_matching","tool":"flag_prohibited",
 "arguments":{"title":"Free desk"},"latency_ms":412.7,"ok":true,"error":null}
{"event":"agent_run","task":"run_matching","tools_used":["flag_prohibited","match_wishlist"],
 "iterations":3,"input_tokens":2841,"output_tokens":205,"latency_ms":3180.4}
```

Runs are also persisted to `agent_runs` (task, status, tool-call count, tokens,
latency, error), which is what the budget guard counts and what you query when
somebody asks where the money went.

### Budget guard

`AGENT_DAILY_BUDGET` (default 20) caps agent runs per user per rolling 24h. The
orchestrator defines a `BudgetGuard` protocol and calls `check()` *before* any API
request; the backend supplies the DB-backed implementation, so the orchestrator
stays database-free. Over budget: `429` on the interactive endpoint, silently
skipped for background work. `AGENT_DAILY_BUDGET=0` disables the AI layer entirely.

### Graceful degradation

| Failure | What happens |
|---|---|
| No `ANTHROPIC_API_KEY` | AI features off; everything else normal; `/agent/*` → 503 |
| MCP server down | `AgentUnavailable`; listing creation unaffected |
| Claude 429 / 5xx / timeout | 3 attempts, exponential backoff (0.5s, 1s) |
| Claude 400 / 401 | fails immediately — a bad request will not improve on a retry |
| Moderation check fails | listing is **not** flagged (an outage must not hide listings) |
| Matching fails | no notifications; the listing is live regardless |
| Pickup draft fails | `drafted_message: null`; owner email still provided |
| Background task raises | logged; the created listing is untouched |

Each row has a test.

---

## API

All routes are under `/api/v1`. Interactive docs: `/docs`.

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | → user + access & refresh tokens |
| POST | `/auth/login` | identical 401 for unknown email and wrong password |
| POST | `/auth/refresh` | refresh tokens only; an access token is rejected |
| GET | `/auth/me` | |
| GET | `/listings` | `category`, `status`, `search`, `mine`, `limit`, `offset` |
| POST | `/listings` | multipart; triggers moderation + matching in the background |
| GET/PATCH/DELETE | `/listings/{id}` | owner only for mutations; DELETE is a soft remove |
| POST | `/agent/draft-listing` | multipart photo → AI-drafted fields for confirmation |
| POST | `/listings/{id}/claims` | |
| GET | `/listings/{id}/claims` | owner only |
| GET | `/claims/mine` | the claimer's own claims + pickup details |
| PATCH | `/claims/{id}` | `accept` / `decline` / `cancel` / `complete` |
| GET/POST | `/wishlist`, DELETE `/wishlist/{id}` | |
| GET | `/notifications`, PATCH `/notifications/{id}/read` | polled every 30s |

Claim rules: at most one accepted claim per listing (accepting declines the rest in
the same transaction), an owner cannot claim their own listing, only the owner
accepts/declines, only the claimer cancels, and the owner's email is released only
once a claim is accepted.

---

## Configuration

See `.env.example`. The ones that matter:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | postgres on localhost | SQLAlchemy URL |
| `JWT_SECRET` | — | **must be ≥32 bytes**, or the app refuses to boot |
| `ANTHROPIC_API_KEY` | empty | empty disables the AI layer |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` | vision-capable; used by tools and orchestrator |
| `AGENT_DAILY_BUDGET` | `20` | agent runs per user per 24h; `0` disables |
| `MATCH_SCORE_THRESHOLD` | `0.6` | minimum score for a wishlist notification |
| `MCP_TRANSPORT` | `http` | `http` (compose) or `stdio` (subprocess) |

---

## Repository layout

```
backend/            FastAPI app
  app/routers/      thin HTTP layer; no business logic
  app/services/     all logic, incl. agent_service.py (the bridge)
  app/models/       SQLAlchemy 2.x models
  app/core/         security.py (JWT + bcrypt), deps, form helpers
  alembic/          migrations
  tests/            171 tests
agent/              the orchestrator (a separate deployable)
  orchestrator.py   the agentic loop
  prompts.py        one system prompt per task
mcp-server/         the MCP tool server
  server.py         registers the five tools; stdio + HTTP transports
  tools/            one module per tool
  tests/            31 tests
frontend/           React 18 + TypeScript + Vite + Tailwind
uploads/            photo volume (swappable for GCS behind StorageService)
docker-compose.yml  api · frontend · postgres · mcp-server
```

---

## Implementation notes

Things a reader might otherwise trip over:

- **`bcrypt` is used directly, not via passlib.** passlib 1.7.4 is broken against
  bcrypt 5.x on Python 3.13 — its backend-detection probe raises
  `ValueError: password cannot be longer than 72 bytes` at import. Same algorithm,
  same cost factor, no unmaintained dependency. That 72-byte limit is also surfaced
  as the password field's `max_length`, so an over-long password is a 422 rather
  than a silently truncated secret.
- **`JSONB` on PostgreSQL, `JSON` elsewhere** via
  `sa.JSON().with_variant(JSONB, "postgresql")`, so the test suite runs on SQLite
  with no daemon while production keeps real JSONB.
- **Migration `0001` is hand-written.** Autogenerate flattens the JSONB variant, and
  PostgreSQL enums shared by two tables (`category`) need creating once up front
  rather than inline per column. `alembic revision --autogenerate` produces an empty
  diff against both migrations, which is the check that the models and migrations
  agree.
- **The MCP server duplicates the category/condition enum values** so it does not
  import the backend package. A test imports the real enums and asserts the lists
  match, so the duplication cannot drift.
- **`agent_runs` is a seventh table** beyond the specified data model. The per-user
  budget guard needs a queryable count of runs per user per day; a log file cannot
  be queried from the request path. It doubles as the run audit trail.
- **A Pydantic model annotated `Form()` is only flattened by FastAPI when it is the
  sole body parameter.** Next to `File()` uploads it is embedded under its own key,
  so multipart endpoints declare their fields explicitly and validate through the
  model (`app/core/forms.py`) to keep 422 bodies shaped like the JSON endpoints'.
- **Hidden listings return 404, not 403** — to a non-owner, a flagged or removed
  listing must not confirm that it exists. Same for another user's wishlist item or
  notification.
