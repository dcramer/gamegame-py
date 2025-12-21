# GameGame Backend

Python backend for GameGame - an LLM-powered board game rules assistant.

See the [main README](../README.md) for full documentation.

## Quick Start

```bash
# Install dependencies
uv sync --all-extras

# Run development server
uv run uvicorn gamegame.main:app --reload --port 8000

# Run tests
uv run pytest

# Run linting
uv run ruff check .
```

## Structure

```
src/gamegame/
├── main.py          # FastAPI app
├── config.py        # Settings
├── database.py      # Database setup
├── models/          # SQLModel models
├── api/             # Routes
├── services/        # Business logic
└── cli/             # CLI commands
```
