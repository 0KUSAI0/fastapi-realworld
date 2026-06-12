# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a FastAPI implementation of the [RealWorld](https://github.com/gothinkster/realworld) Conduit spec, extended with three AI features on top of the original backend:

- **AI article assistant** — `POST /api/articles/ai/analyze` calls a vLLM OpenAI-compatible Qwen3-8B service
- **AI comment moderation** — `POST /api/articles/{slug}/comments/ai/moderate`; normal comment creation can also moderate in `log` or `block` mode
- **AI related article recommendations** — `GET /api/articles/{slug}/recommendations` uses `sentence-transformers/all-MiniLM-L6-v2` embeddings + pgvector cosine search

## Local Setup (This Machine)

PostgreSQL with pgvector runs on port **15432**. Demo DB: `rwdb`. Test DB: `rwtest`. Keep them separate — demo data must not affect test counts.

**Always prefix commands with `DEBUG=true`** on this shared machine. A shell-level `DEBUG=release` (or any non-boolean string) overrides `.env` and will break startup.

Copy `.env.example` to `.env` before first run.

## Common Commands

```bash
# Run migrations (demo database)
DEBUG=true .venv/bin/alembic upgrade head

# Start the backend (pick a free port, e.g. 8010)
DEBUG=true .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

# Serve the static demo frontend
cd demo && ../.venv/bin/python -m http.server 5173 --bind 127.0.0.1

# Run all tests (against rwtest, not rwdb)
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
  DEBUG=true .venv/bin/python -m pytest -q --no-cov -n 0

# Run a single test
DATABASE_URL=postgresql://postgres:postgres@localhost:15432/rwtest \
  DEBUG=true .venv/bin/python -m pytest tests/test_api/test_routes/test_users.py::test_user_can_not_take_already_used_credentials

# Linting / formatting
.venv/bin/black app tests
.venv/bin/isort app tests
.venv/bin/flake8 app tests
```

Tests use fake LLM clients by default (`ai_comment_moderation_mode=off`, `ai_article_review_on_publish=false` in `TestAppSettings`). Real model behaviour must be verified manually through the demo UI.

## Architecture

### Request Flow

`app/main.py` → `app/api/routes/api.py` (router aggregation) → individual route handlers → service layer → repository layer → PostgreSQL via `asyncpg`/`databases`.

Settings are loaded via `app/core/config.py` using a `functools.lru_cache`-wrapped factory that selects `AppSettings` (prod/dev) or `TestAppSettings` based on `APP_ENV`.

### Layers

| Layer | Location | Purpose |
|---|---|---|
| Routes | `app/api/routes/` | FastAPI handlers, request/response schema binding |
| Dependencies | `app/api/dependencies/` | FastAPI `Depends` factories for auth, DB, AI services |
| Repositories | `app/db/repositories/` | All DB access (asyncpg `Connection` + aiosql named queries) |
| Services | `app/services/` | Non-CRUD logic: JWT, auth, article slug, AI features |
| Models | `app/models/domain/` | Core domain objects (Pydantic); `app/models/schemas/` for request/response shapes |

### Database Access Pattern

Named SQL queries live in `app/db/queries/sql/*.sql` (aiosql format) and are accessed through the `queries` object from `app/db/queries/queries.py`. The type stubs in `queries.pyi` document all named query signatures.

Complex queries (e.g. filtered article lists, embedding similarity search) are built dynamically using **pypika** directly in the repository layer. Raw asyncpg `connection.execute/fetch/fetchrow` is used for pgvector operations.

### AI Services (`app/services/ai/`)

**Cross-encoder reranking** (`cross_reranker.py`): `CrossReranker` calls the LLM to score each (source, candidate) article pair for pairwise relevance. `score_pairs()` runs all pairs concurrently behind an `asyncio.Semaphore(3)` to bound vLLM load; any failed call returns `None` (graceful degradation). The `ArticleRecommendationService` integrates this as a two-stage pipeline: vector search for top-20 recall, then LLM cross-reranking for precision. Combined score = `0.35 × embedding + 0.65 × LLM`. Results are cached in `recommendation_reason_cache` (DB table) keyed by `(source_id, target_id, model_name)` so subsequent requests skip the LLM.

**Article polish** (`article_polish.py`): `ArticlePolishService.polish()` runs a three-stage Critique → Revise → Verify pipeline. Stage 1 (Critic) identifies specific issues; Stage 2 (Writer) rewrites to fix them; Stage 3 (Verifier) scores whether the issues were addressed (0–1). If the Verifier score is below `0.65`, the Verifier's feedback is merged into the critique and Stage 2 re-runs (max 2 iterations total). The best-scoring revision is returned together with a sentence-level diff computed via Python's `difflib.SequenceMatcher`.

**Original AI services:**

- `llm_client.py` — `LLMClient` wraps `AsyncOpenAI` pointing at the local vLLM endpoint; implements a two-turn JSON repair loop for structured outputs (all AI services build on this)
- `article_assistant.py` — `ArticleAssistantService` calls `LLMClient.generate_json()` for structured article analysis
- `comment_moderation.py` — `CommentModerationService` handles `off`/`log`/`block` modes
- `embedding_client.py` — `EmbeddingClient` loads `sentence-transformers/all-MiniLM-L6-v2` locally; falls back to deterministic hash embeddings when `EMBEDDING_FALLBACK_ENABLED=true`
- `article_recommendation.py` — `ArticleRecommendationService` upserts embeddings into `article_embeddings` (pgvector) and queries with `<=>` cosine distance

### New API Endpoints

| Endpoint | Description |
|---|---|
| `POST /api/articles/ai/polish` | Critique → Revise → Verify pipeline; body `{body, instruction}`, returns polished text + sentence diff |
| `GET /api/articles/{slug}/recommendations` | Two-stage vector recall + LLM cross-reranking; results include LLM-generated Chinese reasons |

### New Tables (Migrations)

Applied on top of the original `fdf8821871d7_main_tables.py`:
- `8f2f3fbbd9a6` — `article_embeddings` (pgvector), `article_moderation_logs`
- `9a41d8ce7b31` — `review_status` column on moderation logs
- `c2b7d4a1f3e2` — `content_status` column on articles/comments
- `d7f1a2b3c4e5` — `content_reports`, `content_audit_logs` (governance workflow)
- `e1f4c7a8b9d0` — `comment_likes`
- `b3c5e7a9f1d2` — `recommendation_reason_cache` (LLM cross-reranker output cache)

### Admin API

`app/api/routes/admin.py` exposes `/api/admin/*` endpoints gated by `ADMIN_USERNAMES` (list in settings). Admin users can moderate articles/comments, review AI moderation decisions, and manage content reports via `AdminRepository` and `GovernanceRepository`.

### Articles Route Split

`app/api/routes/articles/` is split into:
- `articles_resource.py` — CRUD + AI analyze endpoint + recommendations
- `articles_common.py` — feed endpoint
- `api.py` — aggregates both into one router

### JWT Auth

`Authorization: Token <jwt>` header. The `jwt_token_prefix` setting (default `"Token"`) must match client usage. Auth is enforced via `get_current_user_authorizer()` dependency factory in `app/api/dependencies/authentication.py`.

## Key Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL DSN |
| `SECRET_KEY` | JWT signing key |
| `LLM_BASE_URL` | vLLM endpoint (default `http://127.0.0.1:8000/v1`) |
| `LLM_MODEL` | Model name sent to vLLM (default `qwen3-8b`) |
| `EMBEDDING_MODEL` | Sentence-transformer model name |
| `EMBEDDING_ALLOW_DOWNLOAD` | Set `false` to prevent HuggingFace downloads |
| `EMBEDDING_FALLBACK_ENABLED` | Use hash-based fallback when model unavailable |
| `AI_COMMENT_MODERATION_MODE` | `off` / `log` / `block` |
| `AI_ARTICLE_REVIEW_ON_PUBLISH` | Block articles failing AI review before insertion |
| `AI_ARTICLE_MIN_CONTENT_SCORE` | Minimum score to allow article creation |
| `ADMIN_USERNAMES` | JSON list of admin usernames, e.g. `["admin"]` |
