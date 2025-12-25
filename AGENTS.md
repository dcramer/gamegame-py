# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

GameGame is an LLM-powered board game assistant that helps players understand game rules. It implements a RAG (Retrieval-Augmented Generation) system with hybrid search combining full-text search and semantic embeddings.

**Tech Stack:**
- **Backend**: Python 3.12+, FastAPI, SQLModel (SQLAlchemy 2.0 + Pydantic)
- **Frontend**: React 19, React Router 7 (SSR framework mode), Vite, TypeScript
- **Database**: PostgreSQL 16 with pgvector extension
- **Task Queue**: SAQ (Redis-based async tasks)
- **Package Manager**: uv (backend), npm (frontend)
- **Type Checking**: ty + mypy (backend)
- **Linting/Formatting**: Ruff (backend), Biome (frontend)

## Development Commands

This project uses [mise](https://mise.jdx.dev/) for task running and tool version management.
Run `mise tasks` to see all available commands.

### Setup
```bash
mise install                  # Install Python, Node, uv (first time only)
mise setup                    # Install deps, start Docker, run migrations
```

### Running the Application
```bash
mise dev                      # Start both backend and frontend
mise backend                  # Backend only (http://localhost:8000)
mise frontend                 # Frontend only (http://localhost:5173)
mise worker                   # Background task worker
```

### Database Operations
```bash
mise migrate                  # Apply migrations
mise migrate:create "description"  # Generate new migration
mise migrate:down             # Rollback last migration
mise migrate:history          # Show migration history
mise db:reset                 # Drop and recreate database (destructive!)
```

### Code Quality
```bash
mise lint                     # Run Ruff + Biome linters
mise lint:fix                 # Auto-fix linting issues
mise format                   # Format with Ruff + Biome
mise typecheck                # Run ty + tsc
mise check                    # All checks (lint, typecheck, test)
```

### CLI Commands

The CLI is built with Typer. Run commands via:
```bash
mise cli users list
mise cli users create user@example.com --admin
mise cli users grant-admin user@example.com
mise cli users login-url user@example.com
mise cli games list
```

Or directly:
```bash
cd backend && uv run gamegame users list
cd backend && uv run gamegame games create "Game Name" --slug game-name
```

### Testing
```bash
mise test                     # Run all tests
mise test:cov                 # With coverage report
mise test:api                 # API tests only
mise test:services            # Service tests only
```

**Test Philosophy**: Only mock external APIs (OpenAI, Mistral). Use real local services (PostgreSQL, Redis).

**Test Database**: Runs on port 5433, separate from dev database on 5432.

## Architecture

### Database Schema

The system uses PostgreSQL with pgvector. Core tables:

- **users**: User accounts (email, name, isAdmin)
- **games**: Board game metadata (name, slug, year, imageUrl, bggId)
- **resources**: Game rulebooks/PDFs (content as markdown, processing status)
- **fragments**: Text chunks with embeddings for RAG search
  - Each resource is split into ~1000 character chunks
  - Vector embedding (1536 dimensions via OpenAI text-embedding-3-small)
  - Full-text search vector (PostgreSQL tsvector)
  - HNSW index for vector similarity, GIN index for full-text
- **embeddings**: Separate table for HyDE (Hypothetical Document Embeddings)
  - Content embeddings: One per fragment
  - Question embeddings: Up to 5 synthetic questions per fragment
- **attachments**: Images extracted from PDFs
  - Stored in local filesystem or S3
  - Metadata: type, mimeType, pageNumber, bbox, description
- **verification_tokens**: Magic link authentication tokens

### SQLModel Models

Models are defined in `backend/src/gamegame/models/`. Key patterns:

```python
# Using pgvector with SQLModel
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlmodel import SQLModel, Field

class Fragment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    content: str

    # Vector embedding - use sa_column for custom types
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(1536))
    )

    # Full-text search vector
    search_vector: Any | None = Field(
        default=None,
        sa_column=Column(TSVECTOR)
    )
```

### RAG System

The search uses **Hybrid Reciprocal Rank Fusion (RRF)** combining:
1. **Full-text search**: PostgreSQL's `ts_rank_cd` and `websearch_to_tsquery`
2. **Semantic search**: Inner product on vector embeddings
3. **HyDE search**: Search against synthetic question embeddings
4. Results fused using RRF with k=50, returning top results

Implementation: `backend/src/gamegame/ai/search.py`

### AI Prompt System

The LLM is given structured tools:
- `search_resources`: Search knowledge base using hybrid search
- `search_images`: Find relevant images/diagrams
- `list_resources`: List available rulebooks for a game
- `get_attachment`: Retrieve attachment by ID

Response format is strictly enforced JSON with:
- `answer`: Markdown-formatted response
- `resources`: Array of resource references with citations
- `followUps`: Suggested follow-up questions

The system only answers four categories of questions:
1. **Gameplay Questions**: Rules, setup, mechanics
2. **Knowledge Questions**: Available resources
3. **External Resource Questions**: Where to find more info
4. **GameGame Questions**: About the system itself

### API Architecture

REST API with JWT authentication:

#### Auth Endpoints (`/api/auth/`)
- `POST /login` - Request magic link
- `POST /verify` - Verify token, get JWT
- `GET /me` - Current user info
- `POST /logout` - Logout

#### Game Endpoints (`/api/games/`)
- `GET /` - List all games
- `GET /{id_or_slug}` - Get game by ID or slug
- `POST /` - Create game (admin)
- `PATCH /{id}` - Update game (admin)
- `DELETE /{id}` - Delete game (admin)

#### Resource Endpoints (`/api/games/{id}/resources/` and `/api/resources/`)
- `GET /api/games/{id}/resources` - List resources for a game
- `POST /api/games/{id}/resources` - Upload PDF resource (admin)
- `GET /api/resources/{id}` - Get resource by ID
- `PATCH /api/resources/{id}` - Update resource (admin)
- `DELETE /api/resources/{id}` - Delete resource (admin)
- `POST /api/resources/{id}/reprocess` - Reprocess resource (admin)

#### Chat Endpoint (`/api/games/{id}/chat`)
- `POST` - Stream AI chat response (SSE)

### Authentication

**JWT-based magic link authentication** (passwordless):

1. User provides email → `POST /api/auth/login`
2. Server generates verification token (hex string)
3. Token stored in `verification_tokens` table, expires in 15 minutes
4. User clicks link → `POST /api/auth/verify`
5. Server validates token, creates JWT
6. JWT returned in response, client stores in localStorage
7. JWT payload: `userId`, `email`, `isAdmin`
8. JWT expires in 30 days

**Dependency Injection Pattern:**
```python
from gamegame.api.deps import CurrentUser, AdminUser, SessionDep

@router.get("/protected")
async def protected_route(user: CurrentUser):
    # user is guaranteed to be authenticated
    pass

@router.post("/admin-only")
async def admin_route(user: AdminUser):
    # user is guaranteed to be admin
    pass
```

### Background Tasks

Uses SAQ (Simple Async Queue) with Redis for durable task processing.

**PDF Processing Pipeline** (6 stages):
1. **INGEST**: Extract text/images using Mistral OCR
2. **VISION**: Analyze images with GPT-4o vision
3. **CLEANUP**: Clean markdown with LLM
4. **METADATA**: Generate resource metadata (title, description)
5. **EMBED**: Generate embeddings and store fragments
6. **FINALIZE**: Mark resource as ready

Task definitions in `backend/src/gamegame/tasks/`.

### File Structure

```
backend/
├── src/gamegame/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entrypoint
│   ├── config.py            # Pydantic settings
│   ├── database.py          # Async SQLAlchemy setup
│   │
│   ├── models/              # SQLModel database models
│   │   ├── user.py
│   │   ├── game.py
│   │   ├── resource.py
│   │   ├── fragment.py
│   │   ├── embedding.py
│   │   └── attachment.py
│   │
│   ├── schemas/             # Pydantic request/response schemas
│   │   └── common.py        # Pagination, errors
│   │
│   ├── api/                 # FastAPI routes
│   │   ├── router.py        # Main router
│   │   ├── deps.py          # Dependency injection
│   │   ├── auth.py
│   │   ├── games.py
│   │   └── health.py
│   │
│   ├── services/            # Business logic
│   │   └── auth.py          # JWT creation/verification
│   │
│   ├── ai/                  # AI/LLM code
│   │   ├── client.py        # OpenAI client wrapper
│   │   ├── embeddings.py    # Embedding generation
│   │   ├── search.py        # Hybrid search
│   │   ├── prompts.py       # System prompts
│   │   └── tools.py         # AI tool definitions
│   │
│   ├── tasks/               # Background tasks
│   │   ├── worker.py        # SAQ worker setup
│   │   └── ingest.py        # PDF processing
│   │
│   ├── cli/                 # Typer CLI
│   │   └── __init__.py
│   │
│   └── utils/               # Utilities
│       ├── chunking.py      # Text splitting
│       └── markdown.py      # Markdown processing
│
├── migrations/              # Alembic migrations
├── tests/                   # pytest test suite
├── pyproject.toml           # Project config
└── alembic.ini              # Alembic config

frontend/
├── app/
│   ├── root.tsx             # Root layout with providers
│   ├── routes.ts            # Route configuration
│   ├── entry.client.tsx     # Client hydration entry
│   ├── entry.server.tsx     # Server rendering entry
│   ├── api/
│   │   ├── client.ts        # Type-safe API client
│   │   └── types.ts         # TypeScript types
│   ├── routes/              # File-based routing
│   │   ├── _index.tsx       # Home page
│   │   ├── games._index.tsx
│   │   ├── games.$gameIdOrSlug.tsx
│   │   ├── auth.signin.tsx
│   │   ├── admin.tsx        # Admin layout
│   │   └── admin.*.tsx      # Admin sub-routes
│   ├── components/
│   │   ├── layout.tsx
│   │   ├── admin-layout.tsx
│   │   └── chat/            # Chat components
│   ├── hooks/               # Custom React hooks
│   └── contexts/            # Auth and toast contexts
├── package.json
├── react-router.config.ts
├── vite.config.ts
└── biome.json
```

## PDF Extraction

The system uses **Mistral OCR API** for PDF extraction:
- Fast: 3-5 seconds per PDF
- High quality: Preserves structure, tables, markdown
- Native page numbers
- Cost: ~$0.001/page
- Requires: `MISTRAL_API_KEY`

## Data Storage and Rendering

### PDF Processing Pipeline

1. **PDF Extraction** (`services/pdf.py`)
   - Mistral OCR extracts text as markdown and images
   - Images stored with bounding box metadata

2. **Attachment Storage** (`services/storage.py`)
   - Images saved to local filesystem or S3
   - Database records with stable IDs
   - Path: `uploads/{prefix}/{id}.{ext}`

3. **Smart Chunking** (`utils/chunking.py`)
   - Small pages (<1500 chars): Keep as single chunk
   - Multi-section pages: Split by section boundaries
   - Large sections: RecursiveCharacterTextSplitter, 1000 chars, 100 overlap
   - Metadata preserved: pageNumber, section, images

4. **Embedding Generation**
   - Model: `text-embedding-3-small` (1536 dimensions)
   - Content embeddings: One per fragment
   - HyDE embeddings: Up to 5 synthetic questions per fragment

### Attachment Reference Syntax

In markdown content, images use custom syntax:
```markdown
![alt text](attachment://{databaseId})
```

The LLM can call `get_attachment(id)` to resolve the actual URL.

## Environment Variables

Required:
- `DATABASE_URL`: PostgreSQL with asyncpg driver
- `OPENAI_API_KEY`: For embeddings and chat
- `MISTRAL_API_KEY`: For PDF OCR
- `SESSION_SECRET`: JWT signing secret (32+ chars)

Optional:
- `REDIS_URL`: Task queue (default: `redis://localhost:6379`)
- `STORAGE_BACKEND`: `local` or `s3`
- `STORAGE_PATH`: Local storage path
- `ENVIRONMENT`: `development`, `production`, `test`

## Testing Guidelines

### Philosophy
- Only mock external APIs (OpenAI, Mistral, BGG)
- Use real PostgreSQL for database tests
- Test database on port 5433 (separate from dev)
- Each test gets a fresh transaction that rolls back

### Patterns

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_game(admin_client: AuthenticatedClient):
    response = await admin_client.post(
        "/api/games",
        json={"name": "Test Game"},
    )
    assert response.status_code == 201
    assert response.json()["slug"] == "test-game"
```

### Fixtures

Available fixtures in `tests/conftest.py`:
- `session` - Database session with auto-rollback
- `client` - AsyncClient for API requests
- `user` - Test user
- `admin_user` - Test admin user
- `auth_headers` - Authorization headers for user
- `admin_headers` - Authorization headers for admin
- `authenticated_client` - Client with user auth
- `admin_client` - Client with admin auth
- `game` - Test game

## Important Notes

- **Async everywhere**: All database operations use async/await
- **Type safety**: Use Pydantic models for all API input/output
- **pgvector**: Vector operations require the pgvector extension
- **Migrations**: Always use Alembic, never `db:push` in production
- **Testing**: Run against real PostgreSQL, not SQLite
- The embedding version should be tracked to allow re-indexing
- BGG API has 5-second rate limits between requests

## Code Style

- Follow Ruff defaults (based on Black formatting)
- Type hints required for function signatures
- Use `async def` for all database operations
- Prefer dependency injection over global state
- Keep business logic in `services/`, routes thin
- Use Pydantic for all external data validation
