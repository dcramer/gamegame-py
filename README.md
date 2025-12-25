# GameGame

An LLM-powered board game assistant that helps players understand game rules using RAG (Retrieval-Augmented Generation) with hybrid search.

## Quick Start

### Prerequisites
- Docker and Docker Compose
- [mise](https://mise.jdx.dev/) (manages Python, Node.js, and uv automatically)

```bash
# Install mise (if not already installed)
curl https://mise.run | sh

# Add to your shell (bash example, see mise docs for other shells)
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
source ~/.bashrc
```

### Setup

```bash
# 1. Clone and enter directory
cd gamegame-py

# 2. Install tools (Python 3.12, Node 20, uv) and dependencies
mise install

# 3. Configure environment variables
cp .env.example .env
```

Edit `.env` and add your API keys:
```bash
# Required for core functionality
OPENAI_API_KEY=sk-...              # From platform.openai.com
MISTRAL_API_KEY=...                # From console.mistral.ai
SESSION_SECRET=...                 # Generate: openssl rand -base64 32
```

```bash
# 4. Run setup (starts Docker, installs deps, runs migrations)
mise setup

# 5. Create an admin user
mise cli users create your-email@example.com --admin

# 6. Start development servers
mise dev
```

Visit:
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/api/docs

### First Login

After starting the dev server, generate a magic link:
```bash
mise cli users login-url your-email@example.com
```
Click the link to sign in.

## Common Commands

Run `mise tasks` to see all available commands.

### Development
```bash
mise dev              # Start both backend and frontend
mise backend          # Start backend only (http://localhost:8000)
mise frontend         # Start frontend only (http://localhost:5173)
mise worker           # Start background task worker
```

### Database Management
```bash
mise migrate                         # Apply pending migrations
mise migrate:create "add users table" # Create new migration
mise migrate:down                    # Rollback last migration
mise migrate:history                 # Show migration history
mise db:reset                        # Drop and recreate database (destructive!)
```

### Docker Services
```bash
mise up               # Start PostgreSQL and Redis
mise down             # Stop Docker services
mise up:test          # Start test database only
```

### CLI Tools

The CLI handles common admin tasks:

```bash
mise cli users list
mise cli users create user@example.com --admin
mise cli users grant-admin user@example.com
mise cli users login-url user@example.com
mise cli games list
```

### Code Quality
```bash
mise lint             # Run linters (Ruff + Biome)
mise lint:fix         # Auto-fix linting issues
mise format           # Format code (Ruff + Biome)
mise typecheck        # Run type checkers (ty + tsc)
mise check            # Run all checks (lint, typecheck, test)
```

### Testing
```bash
mise test             # Run all tests
mise test:cov         # Run tests with coverage report
mise test:api         # Run API tests only
mise test:services    # Run service tests only
```

## Documentation

- **[CLAUDE.md](./CLAUDE.md)** - Complete architecture, development guide, and AI assistant context

## Tech Stack

### Backend
- **Framework**: FastAPI with async/await
- **ORM**: SQLModel (SQLAlchemy 2.0 + Pydantic)
- **Database**: PostgreSQL 16 with pgvector extension
- **Migrations**: Alembic
- **Task Queue**: SAQ (Redis-based async tasks)
- **Package Manager**: uv
- **Type Checking**: ty
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
├── mise.toml                 # Development tasks and tool versions
└── CLAUDE.md                 # AI agent guidance
```

## Troubleshooting

### Database won't start
```bash
# Check if port 5432 is already in use
lsof -i :5432

# Reset Docker containers
mise down
mise up
```

### Migrations fail
```bash
# Ensure database is running
docker compose ps

# Reset database and re-run migrations
mise db:reset
```

### Import errors
```bash
# Reinstall dependencies
mise install
```

### Tests fail with database errors
```bash
# Ensure test database is running
mise up:test

# Run migrations on test database
cd backend && DATABASE_URL=$DATABASE_URL_TEST uv run alembic upgrade head
```

### mise not found after install
```bash
# Ensure mise is activated in your shell
# For bash:
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc
source ~/.bashrc

# For zsh:
echo 'eval "$(~/.local/bin/mise activate zsh)"' >> ~/.zshrc
source ~/.zshrc
```

## License

MIT
