# GameGame

An LLM-powered board game assistant that helps players understand game rules using RAG (Retrieval-Augmented Generation) with hybrid search.

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- Docker and Docker Compose
- uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`)

### Setup

```bash
# 1. Clone and enter directory
cd gamegame-py

# 2. Start PostgreSQL and Redis
docker compose up -d

# 3. Configure environment variables
cp .env.example backend/.env
```

Edit `backend/.env` and add your API keys:
```bash
# Required for core functionality
OPENAI_API_KEY=sk-...              # From platform.openai.com
MISTRAL_API_KEY=...                # From console.mistral.ai
SESSION_SECRET=...                 # Generate: openssl rand -base64 32

# Database (default works with docker-compose)
DATABASE_URL=postgresql+asyncpg://gamegame:gamegame@localhost:5432/gamegame
```

```bash
# 4. Run setup (installs deps, runs migrations)
make setup

# 5. Create an admin user
make create-admin email="your-email@example.com"

# 6. Start development servers
make dev
```

Visit:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/api/docs

### First Login

After starting the dev server, generate a magic link:
```bash
make cli cmd="users login-url your-email@example.com"
```
Click the link to sign in.

## Common Commands

### Development
```bash
make dev              # Start both backend and frontend
make backend          # Start backend only (http://localhost:8000)
make frontend         # Start frontend only (http://localhost:5173)
make worker           # Start background task worker
```

### Database Management
```bash
# Daily operations
make db-reset         # Drop and recreate database (destructive!)
make migrate          # Apply pending migrations

# Schema changes
make migrate-create name="add users table"  # Create new migration
make migrate-down     # Rollback last migration
make migrate-history  # Show migration history
```

### CLI Tools

The CLI handles common admin tasks:

```bash
# User management
make cli cmd="users create user@example.com --admin"
make cli cmd="users grant-admin user@example.com"
make cli cmd="users login-url user@example.com"

# Game management
make cli cmd="games list"
```

### Code Quality
```bash
make lint             # Run Ruff linter
make format           # Format code with Ruff
make typecheck        # Run ty and mypy type checkers
make check            # Run all checks (lint, typecheck, test)
```

### Testing
```bash
make test             # Run all tests
make test-cov         # Run tests with coverage report
make test-api         # Run API tests only
make test-services    # Run service tests only

# Test database runs on port 5433 (separate from dev)
make up-test          # Start test database
```

### Claude Code Development

For AI-assisted development with browser testing:

```bash
# Install Playwright skill for browser automation
git clone https://github.com/lackeyjb/playwright-skill.git ~/.claude/skills/playwright-skill
cd ~/.claude/skills/playwright-skill/skills/playwright-skill
npm run setup

# Install system dependencies (Ubuntu/Debian/WSL)
sudo apt-get install -y libnss3 libnspr4 libasound2t64 libatk1.0-0 \
  libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2
```

Claude Code can then run browser tests against the dev server automatically.

## Documentation

- **[AGENTS.md](./AGENTS.md)** - Complete architecture, development guide, and AI assistant context
- **[SCAFFOLDING_PLAN.md](./SCAFFOLDING_PLAN.md)** - Migration plan and technology decisions

## Tech Stack

### Backend
- **Framework**: FastAPI with async/await
- **ORM**: SQLModel (SQLAlchemy 2.0 + Pydantic)
- **Database**: PostgreSQL 16 with pgvector extension
- **Migrations**: Alembic
- **Task Queue**: SAQ (Redis-based async tasks)
- **Package Manager**: uv
- **Type Checking**: ty + mypy
- **Linting**: Ruff

### Frontend
- **Framework**: React 19 with TypeScript
- **Router**: React Router 7 (SSR framework mode)
- **Build**: Vite 6
- **Styling**: Tailwind CSS 4
- **UI Components**: Radix UI

### AI/ML
- **Embeddings**: OpenAI text-embedding-3-small (1536 dimensions)
- **Chat**: OpenAI GPT-4o / GPT-4o-mini
- **PDF Extraction**: Mistral OCR API
- **Vector Search**: pgvector with HNSW indexing
- **Full-Text Search**: PostgreSQL tsvector with GIN indexing

## Environment Variables

### Required Variables

| Variable | Description | How to Get |
|----------|-------------|------------|
| `DATABASE_URL` | PostgreSQL connection | Auto-configured with docker-compose |
| `OPENAI_API_KEY` | OpenAI API key for embeddings and chat | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `MISTRAL_API_KEY` | Mistral API for PDF OCR | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) |
| `SESSION_SECRET` | JWT signing secret (32+ chars) | Generate: `openssl rand -base64 32` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `REDIS_URL` | Redis for task queue | `redis://localhost:6379` |
| `STORAGE_BACKEND` | File storage backend | `local` (or `s3`) |
| `STORAGE_PATH` | Local storage path | `./uploads` |
| `ENVIRONMENT` | Environment mode | `development` |
| `SENTRY_DSN` | Error tracking | Disabled |

See [.env.example](./.env.example) for complete list with descriptions.

## Project Structure

```
gamegame-py/
├── backend/
│   ├── src/gamegame/         # Main Python package
│   │   ├── api/              # FastAPI routes
│   │   ├── models/           # SQLModel database models
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic
│   │   ├── ai/               # AI/LLM code (embeddings, search, prompts)
│   │   ├── tasks/            # Background task definitions
│   │   ├── cli/              # Typer CLI commands
│   │   └── utils/            # Utilities
│   ├── migrations/           # Alembic migrations
│   └── tests/                # pytest test suite
│
├── frontend/
│   ├── app/                  # React Router 7 app directory
│   │   ├── api/              # Type-safe API client
│   │   ├── components/       # React components
│   │   ├── routes/           # File-based routing (SSR)
│   │   ├── hooks/            # Custom React hooks
│   │   └── contexts/         # React context providers
│   └── public/               # Static assets
│
├── docker-compose.yml        # PostgreSQL + Redis
├── Makefile                  # Development commands
└── AGENTS.md                 # AI agent guidance
```

## Troubleshooting

### Database won't start
```bash
# Check if port 5432 is already in use
lsof -i :5432

# Reset Docker containers
docker compose down
docker compose up -d
```

### Migrations fail
```bash
# Ensure database is running
docker compose ps

# Reset database and re-run migrations
make db-reset
```

### Import errors
```bash
# Reinstall dependencies
cd backend && uv sync --all-extras
```

### Tests fail with database errors
```bash
# Ensure test database is running
make up-test

# Run migrations on test database
cd backend && DATABASE_URL=$DATABASE_URL_TEST uv run alembic upgrade head
```

## License

MIT
