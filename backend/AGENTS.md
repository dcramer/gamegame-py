# Backend AGENTS.md

This file provides guidance for AI assistants working on the Python backend.

## Quick Reference

```bash
# Development
cd backend
uv run uvicorn gamegame.main:app --reload --port 8000

# Testing
uv run pytest
uv run pytest tests/api/test_games.py -v

# Linting & Formatting
uv run ruff check .
uv run ruff format .

# Type Checking
uvx ty check

# CLI
uv run gamegame users list
uv run gamegame games list

# Migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
```

## Project Structure

```
backend/
├── src/gamegame/
│   ├── main.py              # FastAPI app with lifespan
│   ├── config.py            # Pydantic settings (env vars)
│   ├── database.py          # Async SQLAlchemy engine/session
│   │
│   ├── models/              # SQLModel ORM models
│   ├── schemas/             # Pydantic API schemas
│   ├── api/                 # FastAPI routes
│   ├── services/            # Business logic
│   ├── ai/                  # AI/LLM code
│   ├── tasks/               # Background tasks (SAQ)
│   ├── cli/                 # Typer CLI
│   └── utils/               # Helpers
│
├── migrations/              # Alembic
├── tests/                   # pytest
├── pyproject.toml
└── alembic.ini
```

## Key Patterns

### SQLModel with Custom Types (pgvector, tsvector)

```python
from pgvector.sqlalchemy import Vector
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import TSVECTOR, JSONB
from sqlmodel import SQLModel, Field

class Fragment(SQLModel, table=True):
    __tablename__ = "fragments"

    id: int | None = Field(default=None, primary_key=True)
    content: str

    # Use sa_column for custom PostgreSQL types
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(1536))
    )

    search_vector: Any | None = Field(
        default=None,
        sa_column=Column(TSVECTOR)
    )

    metadata: dict | None = Field(
        default=None,
        sa_column=Column(JSONB)
    )
```

### Async Database Operations

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

async def get_game(session: AsyncSession, game_id: int) -> Game | None:
    stmt = select(Game).where(Game.id == game_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def create_game(session: AsyncSession, game: GameCreate) -> Game:
    db_game = Game.model_validate(game)
    session.add(db_game)
    await session.commit()
    await session.refresh(db_game)
    return db_game
```

### FastAPI Dependencies

```python
from typing import Annotated
from fastapi import Depends
from gamegame.api.deps import SessionDep, CurrentUser, AdminUser

@router.get("/games")
async def list_games(session: SessionDep):
    # session is AsyncSession
    pass

@router.post("/games")
async def create_game(
    game: GameCreate,
    session: SessionDep,
    user: AdminUser,  # Raises 403 if not admin
):
    pass

@router.get("/me")
async def get_me(user: CurrentUser):  # Raises 401 if not authenticated
    return user
```

### Error Handling

```python
from fastapi import HTTPException, status

# Not found
raise HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Game not found"
)

# Validation error
raise HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Invalid input"
)

# Auth error
raise HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"}
)

# Permission error
raise HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail="Admin access required"
)
```

### Pydantic Schemas

```python
from pydantic import BaseModel, Field
from sqlmodel import SQLModel

# For API input/output (not database)
class GameCreate(SQLModel):
    name: str
    slug: str | None = None
    year: int | None = None

class GameRead(SQLModel):
    id: int
    name: str
    slug: str
    year: int | None

class GameUpdate(SQLModel):
    name: str | None = None
    year: int | None = None
```

### Configuration

```python
from gamegame.config import settings

# Access settings
database_url = settings.database_url
openai_key = settings.openai_api_key
is_dev = settings.is_development
```

## Testing

### Test Structure

```
tests/
├── conftest.py          # Fixtures
├── api/
│   ├── test_auth.py
│   ├── test_games.py
│   └── test_health.py
├── services/
│   └── test_auth.py
└── integration/
```

### Writing Tests

```python
import pytest
from httpx import AsyncClient
from tests.conftest import AuthenticatedClient

@pytest.mark.asyncio
async def test_list_games(client: AsyncClient, game: Game):
    response = await client.get("/api/games")
    assert response.status_code == 200
    assert len(response.json()) == 1

@pytest.mark.asyncio
async def test_create_game_requires_admin(
    authenticated_client: AuthenticatedClient
):
    response = await authenticated_client.post(
        "/api/games",
        json={"name": "New Game"},
    )
    assert response.status_code == 403  # Non-admin user

@pytest.mark.asyncio
async def test_create_game(admin_client: AuthenticatedClient):
    response = await admin_client.post(
        "/api/games",
        json={"name": "New Game"},
    )
    assert response.status_code == 201
    assert response.json()["slug"] == "new-game"
```

### Available Fixtures

- `session` - AsyncSession with auto-rollback
- `client` - AsyncClient for unauthenticated requests
- `user` - Regular test user
- `admin_user` - Admin test user
- `user_token` / `admin_token` - JWT tokens
- `auth_headers` / `admin_headers` - Auth header dicts
- `authenticated_client` - Client with user auth
- `admin_client` - Client with admin auth
- `game` - Sample game fixture

## Migrations

### Creating a Migration

```bash
# After modifying models
uv run alembic revision --autogenerate -m "add new field"

# Review generated migration in migrations/versions/
# Edit if needed (especially for pgvector types)

# Apply
uv run alembic upgrade head
```

### Manual Migration for pgvector

Alembic may not auto-detect Vector types correctly. Add manually:

```python
def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create table with vector column
    op.create_table(
        'fragments',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('embedding', Vector(1536)),
    )

    # Create HNSW index
    op.execute("""
        CREATE INDEX fragment_embedding_idx ON fragments
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
```

## Code Style

- Use `async def` for all I/O operations
- Type hints on all function signatures
- Docstrings for public functions
- Keep route handlers thin, logic in services
- Use Pydantic for all external data validation
- Follow Ruff defaults (Black-compatible)

## Common Issues

### "Cannot find module 'gamegame'"
```bash
# Ensure you're in backend directory with venv active
cd backend
uv sync
```

### pgvector type not recognized
```python
# Register vector type before using
from pgvector.sqlalchemy import Vector
# Import at top of models/__init__.py
```

### Async session issues
```python
# Always use async with
async with get_session_context() as session:
    # do work
    pass

# Or use dependency injection in routes
async def route(session: SessionDep):
    pass
```
