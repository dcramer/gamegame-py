# GameGame Python Migration - Scaffolding Plan

## Overview

Migrate the GameGame board game rules assistant from Next.js to a Python backend with React SPA frontend.

## Technology Stack

| Layer | Technology | Version | Notes |
|-------|------------|---------|-------|
| **Runtime** | Python | 3.12+ | Latest stable |
| **Framework** | FastAPI | 0.115+ | Async, OpenAPI docs |
| **ORM** | SQLModel | 0.0.22+ | SQLAlchemy 2.0 + Pydantic |
| **Database** | PostgreSQL | 16+ | With pgvector extension |
| **Migrations** | Alembic | 1.14+ | SQLAlchemy migrations |
| **Validation** | Pydantic | 2.10+ | Built into SQLModel |
| **Package Manager** | uv | 0.5+ | Fast, Rust-based |
| **Type Checker** | ty + mypy | ty 0.0.1a+ | ty primary, mypy fallback |
| **Linter/Formatter** | Ruff | 0.8+ | Fast, replaces black/isort/flake8 |
| **Testing** | pytest | 8.3+ | With pytest-asyncio, httpx |
| **Task Queue** | SAQ or ARQ | - | Redis-based async tasks |
| **Frontend** | React 19 | - | With React Router 7 SPA |
| **Build Tool** | Vite | 6+ | Frontend bundling |

## Project Structure

```
gamegame-py/
├── backend/
│   ├── src/
│   │   └── gamegame/
│   │       ├── __init__.py
│   │       ├── main.py              # FastAPI app entrypoint
│   │       ├── config.py            # Settings via pydantic-settings
│   │       ├── database.py          # DB engine, session factory
│   │       │
│   │       ├── models/              # SQLModel database models
│   │       │   ├── __init__.py
│   │       │   ├── base.py          # Base model with common fields
│   │       │   ├── user.py
│   │       │   ├── game.py
│   │       │   ├── resource.py
│   │       │   ├── fragment.py
│   │       │   ├── embedding.py
│   │       │   └── attachment.py
│   │       │
│   │       ├── schemas/             # Pydantic request/response schemas
│   │       │   ├── __init__.py
│   │       │   ├── auth.py
│   │       │   ├── game.py
│   │       │   ├── resource.py
│   │       │   └── common.py        # Pagination, errors, etc.
│   │       │
│   │       ├── api/                 # API routes
│   │       │   ├── __init__.py
│   │       │   ├── router.py        # Main router aggregator
│   │       │   ├── deps.py          # Dependency injection
│   │       │   ├── auth.py          # Auth endpoints
│   │       │   ├── games.py         # Game CRUD
│   │       │   ├── resources.py     # Resource management
│   │       │   ├── attachments.py   # Attachment handling
│   │       │   ├── chat.py          # RAG chat endpoint
│   │       │   ├── bgg.py           # BoardGameGeek integration
│   │       │   └── health.py        # Health check
│   │       │
│   │       ├── services/            # Business logic
│   │       │   ├── __init__.py
│   │       │   ├── auth.py          # JWT, magic links
│   │       │   ├── game.py
│   │       │   ├── resource.py
│   │       │   ├── search.py        # Hybrid search (vector + FTS)
│   │       │   ├── embeddings.py    # OpenAI embeddings
│   │       │   ├── pdf.py           # PDF extraction (Mistral)
│   │       │   ├── storage.py       # File storage abstraction
│   │       │   └── bgg.py           # BGG API client
│   │       │
│   │       ├── ai/                  # AI/LLM related code
│   │       │   ├── __init__.py
│   │       │   ├── client.py        # OpenAI client wrapper
│   │       │   ├── prompts.py       # System prompts
│   │       │   ├── tools.py         # AI tool definitions
│   │       │   ├── hyde.py          # Hypothetical document embeddings
│   │       │   └── reranker.py      # Cross-encoder reranking
│   │       │
│   │       ├── tasks/               # Background tasks
│   │       │   ├── __init__.py
│   │       │   ├── worker.py        # Task worker setup
│   │       │   ├── ingest.py        # PDF ingestion pipeline
│   │       │   ├── vision.py        # Image analysis
│   │       │   ├── embed.py         # Embedding generation
│   │       │   └── cleanup.py       # Markdown cleanup
│   │       │
│   │       └── utils/               # Utilities
│   │           ├── __init__.py
│   │           ├── chunking.py      # Text splitting
│   │           ├── markdown.py      # Markdown processing
│   │           └── types.py         # Custom types (Vector, TSVector)
│   │
│   ├── migrations/                  # Alembic migrations
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py              # Fixtures, test DB setup
│   │   ├── factories.py             # Model factories
│   │   ├── api/
│   │   │   ├── test_auth.py
│   │   │   ├── test_games.py
│   │   │   ├── test_resources.py
│   │   │   └── test_chat.py
│   │   ├── services/
│   │   │   ├── test_search.py
│   │   │   └── test_embeddings.py
│   │   └── integration/
│   │       └── test_pdf_pipeline.py
│   │
│   ├── cli/                         # CLI commands
│   │   ├── __init__.py
│   │   └── commands.py              # typer CLI
│   │
│   ├── pyproject.toml               # Project config, deps
│   ├── uv.lock                      # Lockfile
│   ├── alembic.ini                  # Alembic config
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── main.tsx                 # Entry point
│   │   ├── routes.tsx               # React Router config
│   │   ├── api/                     # API client
│   │   │   ├── client.ts
│   │   │   └── types.ts             # Generated from OpenAPI
│   │   ├── components/
│   │   │   ├── ui/                  # Radix UI components
│   │   │   ├── chat.tsx
│   │   │   ├── games-grid.tsx
│   │   │   ├── header.tsx
│   │   │   └── ...
│   │   ├── pages/
│   │   │   ├── home.tsx
│   │   │   ├── game.tsx
│   │   │   ├── admin/
│   │   │   └── auth/
│   │   ├── hooks/
│   │   ├── lib/
│   │   └── styles/
│   │
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── tailwind.config.ts
│
├── docker-compose.yml               # PostgreSQL, Redis
├── Makefile                         # Common commands
├── .env.example
├── .gitignore
└── README.md
```

## Database Schema

SQLModel models with pgvector and tsvector support:

```python
# backend/src/gamegame/models/fragment.py
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import Index
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

class Fragment(SQLModel, table=True):
    __tablename__ = "fragments"

    id: int | None = Field(default=None, primary_key=True)
    game_id: int = Field(foreign_key="games.id", index=True)
    resource_id: int = Field(foreign_key="resources.id", index=True)
    content: str
    type: str = Field(default="text")  # text, image, table
    page_number: int | None = None
    section: str | None = None

    # Vector embedding (1536 dims for text-embedding-3-small)
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(1536))
    )

    # Full-text search vector
    search_vector: str | None = Field(
        default=None,
        sa_column=Column(TSVECTOR)
    )

    # HyDE synthetic questions (JSON)
    synthetic_questions: list[str] | None = Field(default=None, sa_type=JSON)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# Vector similarity index (HNSW for better performance)
fragment_embedding_idx = Index(
    'fragment_embedding_idx',
    Fragment.embedding,
    postgresql_using='hnsw',
    postgresql_with={'m': 16, 'ef_construction': 64},
    postgresql_ops={'embedding': 'vector_cosine_ops'}
)

# Full-text search index (GIN)
fragment_search_idx = Index(
    'fragment_search_idx',
    Fragment.search_vector,
    postgresql_using='gin'
)
```

## Key Configuration Files

### pyproject.toml

```toml
[project]
name = "gamegame"
version = "0.1.0"
description = "LLM-powered board game rules assistant"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlmodel>=0.0.22",
    "asyncpg>=0.30.0",
    "alembic>=1.14.0",
    "pydantic-settings>=2.6.0",
    "pgvector>=0.3.6",
    "openai>=1.57.0",
    "httpx>=0.28.0",
    "python-jose[cryptography]>=3.3.0",
    "passlib>=1.7.4",
    "python-multipart>=0.0.17",
    "saq[web]>=0.22.0",
    "redis>=5.2.0",
    "mistralai>=1.2.0",
    "typer>=0.15.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "pytest-cov>=6.0.0",
    "httpx>=0.28.0",
    "factory-boy>=3.3.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
    "pre-commit>=4.0.0",
]

[project.scripts]
gamegame = "gamegame.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/gamegame"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.3.0",
    "pytest-asyncio>=0.25.0",
    "pytest-cov>=6.0.0",
    "httpx>=0.28.0",
    "factory-boy>=3.3.0",
    "ruff>=0.8.0",
    "mypy>=1.13.0",
    "pre-commit>=4.0.0",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # Pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
    "ARG",    # flake8-unused-arguments
    "SIM",    # flake8-simplify
]
ignore = ["E501"]  # line too long (handled by formatter)

[tool.ruff.format]
quote-style = "double"

[tool.ty]
python-version = "3.12"

[tool.ty.src]
include = ["src", "tests"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
addopts = "-v --tb=short"
```

### docker-compose.yml

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: gamegame
      POSTGRES_PASSWORD: gamegame
      POSTGRES_DB: gamegame
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U gamegame"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

## Implementation Phases

### Phase 1: Project Scaffolding (This Step)
- [ ] Initialize uv project structure
- [ ] Set up pyproject.toml with all dependencies
- [ ] Configure Ruff, ty, mypy
- [ ] Set up docker-compose for PostgreSQL + Redis
- [ ] Create base SQLModel models
- [ ] Initialize Alembic migrations
- [ ] Set up pytest with fixtures
- [ ] Create Makefile with common commands

### Phase 2: Core Backend
- [ ] Implement database connection and session management
- [ ] Create all SQLModel models (users, games, resources, fragments, embeddings, attachments)
- [ ] Write initial Alembic migrations
- [ ] Implement auth service (JWT, magic links)
- [ ] Create FastAPI dependency injection setup
- [ ] Implement health check endpoint

### Phase 3: API Routes
- [ ] Auth endpoints (login, verify, logout, me)
- [ ] Games CRUD endpoints
- [ ] Resources endpoints
- [ ] Attachments endpoints
- [ ] BGG integration endpoints

### Phase 4: AI & Search
- [ ] OpenAI client wrapper
- [ ] Embedding generation service
- [ ] Hybrid search (vector + FTS + RRF)
- [ ] HyDE synthetic question generation
- [ ] Cross-encoder reranking
- [ ] Chat endpoint with streaming

### Phase 5: Background Tasks
- [ ] Set up SAQ worker
- [ ] PDF ingestion pipeline
- [ ] Image analysis with vision model
- [ ] Markdown cleanup
- [ ] Embedding batch processing

### Phase 6: Frontend Migration
- [ ] Initialize Vite + React Router 7 SPA
- [ ] Set up Tailwind + Radix UI
- [ ] Generate TypeScript types from OpenAPI
- [ ] Migrate React components
- [ ] Implement API client
- [ ] Configure static file serving from FastAPI

### Phase 7: Testing & Polish
- [ ] Comprehensive API tests
- [ ] Service layer tests
- [ ] Integration tests
- [ ] CI/CD setup
- [ ] Documentation

## Commands (Makefile)

```makefile
.PHONY: setup dev test lint format migrate

# Initial setup
setup:
	cd backend && uv sync
	cd frontend && npm install
	docker-compose up -d
	cd backend && uv run alembic upgrade head

# Development
dev:
	docker-compose up -d
	cd backend && uv run uvicorn gamegame.main:app --reload --port 8000 &
	cd frontend && npm run dev

# Run backend only
backend:
	cd backend && uv run uvicorn gamegame.main:app --reload --port 8000

# Run tests
test:
	cd backend && uv run pytest

test-cov:
	cd backend && uv run pytest --cov=gamegame --cov-report=html

# Linting & formatting
lint:
	cd backend && uv run ruff check .
	cd backend && uvx ty check

format:
	cd backend && uv run ruff format .
	cd backend && uv run ruff check --fix .

# Type checking
typecheck:
	cd backend && uvx ty check
	cd backend && uv run mypy src

# Database
migrate:
	cd backend && uv run alembic upgrade head

migrate-create:
	cd backend && uv run alembic revision --autogenerate -m "$(name)"

# CLI
cli:
	cd backend && uv run gamegame $(cmd)

# Docker
up:
	docker-compose up -d

down:
	docker-compose down

# Clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
```

## Environment Variables

```bash
# .env.example

# Database
DATABASE_URL=postgresql+asyncpg://gamegame:gamegame@localhost:5432/gamegame

# Redis (for task queue)
REDIS_URL=redis://localhost:6379

# Auth
SESSION_SECRET=your-32-char-secret-here
JWT_ALGORITHM=HS256
JWT_EXPIRATION_DAYS=30

# OpenAI
OPENAI_API_KEY=sk-...

# Mistral (PDF extraction)
MISTRAL_API_KEY=...

# Storage
STORAGE_BACKEND=local  # or "s3"
STORAGE_PATH=./uploads

# App
ENVIRONMENT=development
DEBUG=true
CORS_ORIGINS=["http://localhost:5173"]
```

## Sources & References

### Framework Comparison
- [FastAPI vs Litestar 2025](https://medium.com/@rameshkannanyt0078/fastapi-vs-litestar-2025-which-async-python-web-framework-should-you-choose-8dc05782a276)
- [Litestar vs FastAPI - Better Stack](https://betterstack.com/community/guides/scaling-python/litestar-vs-fastapi/)

### Package Management
- [uv Documentation](https://docs.astral.sh/uv/)
- [Managing Python Projects with uv - Real Python](https://realpython.com/python-uv/)

### Type Checking
- [ty Documentation](https://docs.astral.sh/ty/)
- [ty Type Checker - Real Python](https://realpython.com/python-ty/)

### Database & ORM
- [SQLAlchemy 2.0 Async](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [pgvector-python](https://github.com/pgvector/pgvector-python)
- [SQLModel + pgvector](https://theorashid.github.io/notes/PGVector-+-SQLModel)

### Testing
- [FastAPI Async Tests](https://fastapi.tiangolo.com/advanced/async-tests/)
- [pytest-asyncio Best Practices](https://testdriven.io/blog/fastapi-crud/)

### Frontend
- [React Router 7 SPA Mode](https://reactrouter.com/how-to/spa)
- [Serving React with FastAPI](https://davidmuraya.com/blog/serving-a-react-frontend-application-with-fastapi/)
