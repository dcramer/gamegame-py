# Testing Guide

## Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/api/test_games.py

# Run specific test
uv run pytest tests/api/test_games.py::test_create_game

# Run with output
uv run pytest -v
```

## Writing Tests

### Philosophy

- **Integration-focused**: Test through the HTTP API, not internal functions
- **Minimal mocks**: Use the real database, real services. Only mock external APIs (BGG, LLMs, etc.)
- **Cover user input paths**: Every API endpoint, every user role (anonymous, authenticated, admin)
- **Skip exhaustive edge cases**: Don't test every validation error. One happy path + one error case is usually enough

### Test Structure

Tests go in `tests/api/` mirroring the API structure. Each endpoint module gets a test file.

```
tests/
├── api/
│   ├── test_games.py
│   ├── test_resources.py
│   └── test_auth.py
└── conftest.py
```

### Available Fixtures

From `tests/conftest.py`:

| Fixture | Description |
|---------|-------------|
| `client` | Unauthenticated `AsyncClient` |
| `authenticated_client` | Regular user client (wrapped `AuthenticatedClient`) |
| `admin_client` | Admin user client (wrapped `AuthenticatedClient`) |
| `session` | Database session (auto-rollback after each test) |
| `user` | Regular `User` instance |
| `admin_user` | Admin `User` instance |
| `game` | Sample `Game` instance |

### Example Test

```python
import pytest
from httpx import AsyncClient
from tests.conftest import AuthenticatedClient

@pytest.mark.asyncio
async def test_create_game_requires_admin(authenticated_client: AuthenticatedClient):
    """Regular users cannot create games."""
    response = await authenticated_client.post("/api/games", json={"name": "New Game"})
    assert response.status_code == 403

@pytest.mark.asyncio
async def test_create_game(admin_client: AuthenticatedClient):
    """Admins can create games."""
    response = await admin_client.post("/api/games", json={"name": "New Game", "year": 2024})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Game"
    assert data["slug"] == "new-game-2024"
```

### What to Test

For each endpoint, cover:

1. **Happy path** - The normal success case
2. **Auth requirements** - Anonymous, authenticated, admin as appropriate
3. **Not found** - 404 for invalid IDs (one test per resource type is enough)
4. **Invalid input** - One validation error case if there's interesting validation

### Creating Test Data

Use fixtures or create directly in tests:

```python
@pytest.fixture
async def resource(session: AsyncSession, game: Game) -> Resource:
    """Create a test resource."""
    resource = Resource(
        game_id=game.id,
        name="Test Rulebook",
        url="/uploads/test.pdf",
        status=ResourceStatus.COMPLETED,
        resource_type=ResourceType.RULEBOOK,
    )
    session.add(resource)
    await session.flush()
    return resource
```

### Database Isolation

Each test runs in a transaction that rolls back automatically. Tests can call `session.commit()` - it commits to a SAVEPOINT, not the real database. Tests are fully isolated.
