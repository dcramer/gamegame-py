# GameGame Backend Specification

This document describes all backend behaviors from the original Next.js GameGame project that need to be implemented in the Python/FastAPI backend.

## Executive Summary

GameGame is a board game knowledge platform with:
- RESTful APIs for game/resource management
- Magic link authentication with JWT sessions
- Multi-stage PDF processing pipeline (6 stages)
- Hybrid RAG system combining vector embeddings, full-text search, and LLM reranking
- Image extraction and analysis from PDFs
- Background job processing

---

## 1. API Endpoints

### 1.1 Authentication

#### POST /api/auth/login
Request a magic link for authentication.

**Request:**
```json
{
  "email": "string (required)"
}
```

**Response (200):**
```json
{
  "message": "Check your email for the login link",
  "magic_link": "string|null (dev only)"
}
```

**Behavior:**
- Generate 32-byte hex token
- Token expires in 15 minutes
- Create `verification_tokens` record
- In dev: return magic link in response
- In prod: send email (not yet implemented)

#### POST /api/auth/verify
Verify magic link token and create session.

**Request:**
```json
{
  "token": "string (required)"
}
```

**Response (200):**
```json
{
  "access_token": "string (JWT)",
  "token_type": "bearer",
  "user": { "id", "email", "name", "is_admin" }
}
```

**Behavior:**
- Validate token exists and not expired
- Delete token (one-time use)
- Create user if doesn't exist (name = email prefix, is_admin = false)
- Generate JWT (30 day expiration)

#### GET /api/auth/me
Get current authenticated user.

**Response (200):**
```json
{
  "id": "string",
  "email": "string",
  "name": "string|null",
  "is_admin": "boolean"
}
```

#### POST /api/auth/logout
Logout (client-side token clearing).

**Response (200):**
```json
{
  "message": "Logged out successfully"
}
```

---

### 1.2 Games

#### GET /api/games
List all games with resource counts.

**Response (200):**
```json
[
  {
    "id": "string",
    "name": "string",
    "slug": "string",
    "year": "number|null",
    "image_url": "string|null",
    "bgg_id": "string|null",
    "bgg_url": "string|null",
    "resource_count": "number",
    "created_at": "datetime",
    "updated_at": "datetime"
  }
]
```

#### POST /api/games (Admin)
Create a new game.

**Request:**
```json
{
  "name": "string (required)",
  "year": "number|null",
  "image_url": "string|null",
  "bgg_url": "string|null"
}
```

**Behavior:**
- Generate slug from name + year (kebab-case)
- Extract BGG ID from URL if provided (`/boardgame/(\d+)`)

#### GET /api/games/{game_id_or_slug}
Get single game by ID or slug.

#### PATCH /api/games/{game_id} (Admin)
Update game. Regenerates slug if name/year changes.

#### DELETE /api/games/{game_id} (Admin)
Delete game with cascading delete of:
1. Embeddings (via fragments)
2. Fragments
3. Attachments + blob files
4. Resources
5. Game

---

### 1.3 Resources

#### GET /api/games/{game_id_or_slug}/resources
List all resources for a game.

**Response (200):**
```json
[
  {
    "id": "string",
    "name": "string",
    "description": "string|null",
    "url": "string",
    "version": "number",
    "status": "ready|queued|processing|completed|failed",
    "processing_stage": "string|null",
    "page_count": "number|null",
    "image_count": "number",
    "word_count": "number",
    "resource_type": "rulebook|expansion|faq|errata|reference",
    "fragment_count": "number",
    "created_at": "datetime",
    "updated_at": "datetime"
  }
]
```

#### POST /api/games/{game_id_or_slug}/resources (Admin)
Create resource from file upload or URL.

**Request:** multipart/form-data
- `file`: PDF file (max 100MB) OR
- `url`: External resource URL
- `name`: Optional name (defaults to filename)

**Behavior:**
- Upload file to blob storage at `resources/{resource_id}/source.{ext}`
- Create resource with status='processing'
- Trigger 6-stage processing pipeline
- Return resource with `current_run_id` for tracking

#### GET /api/resources/{resource_id}
Get resource with full content.

#### PATCH /api/resources/{resource_id} (Admin)
Update resource metadata.

#### DELETE /api/resources/{resource_id} (Admin)
Delete resource with cascading delete of embeddings, fragments, attachments.

---

### 1.4 Attachments

#### GET /api/attachments/{attachment_id}
Get attachment metadata.

**Response (200):**
```json
{
  "id": "string",
  "game_id": "string",
  "resource_id": "string",
  "type": "image",
  "mime_type": "string",
  "url": "string",
  "page_number": "number|null",
  "bbox": "[x1, y1, x2, y2]|null",
  "caption": "string|null",
  "description": "string|null (AI-generated)",
  "detected_type": "diagram|table|photo|icon|decorative|null",
  "is_relevant": "boolean|null",
  "ocr_text": "string|null"
}
```

#### PATCH /api/attachments/{attachment_id} (Admin)
Update attachment metadata.

#### POST /api/attachments/{attachment_id}/reprocess (Admin)
Re-analyze attachment with vision model.

---

### 1.5 Chat (RAG)

#### POST /api/games/{game_id_or_slug}/chat
Stream chat responses using RAG search + LLM.

**Request:**
```json
{
  "messages": [
    { "role": "user|assistant", "content": "string" }
  ]
}
```

**Response:** Server-Sent Events (SSE)
```
data: {"type":"text-delta","text":"..."}
data: {"type":"finish","finishReason":"stop","usage":{...}}
```

**Behavior:**
1. Extract last user message
2. Search with RAG (vector + FTS + RRF + reranking)
3. Stream GPT response with context

---

### 1.6 Upload

#### POST /api/upload (Admin)
Upload file to blob storage.

**Query Params:**
- `type`: 'image' (10MB max) or 'pdf' (100MB max)

**Response (200):**
```json
{
  "url": "string",
  "blob_key": "string",
  "size": "number",
  "type": "string (mimetype)"
}
```

---

### 1.7 Health

#### GET /api/health
Health check endpoint.

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": "ISO8601",
  "checks": { "database": "ok" }
}
```

---

## 2. Database Schema

### 2.1 Users
```sql
CREATE TABLE users (
  id VARCHAR PRIMARY KEY,
  email VARCHAR(255) UNIQUE NOT NULL,
  name TEXT,
  is_admin BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
```

### 2.2 Verification Tokens
```sql
CREATE TABLE verification_tokens (
  identifier VARCHAR PRIMARY KEY,  -- email
  token VARCHAR NOT NULL,
  expires TIMESTAMPTZ NOT NULL
);
```

### 2.3 Games
```sql
CREATE TABLE games (
  id VARCHAR PRIMARY KEY,
  name TEXT NOT NULL,
  year INTEGER,
  slug VARCHAR UNIQUE NOT NULL,
  image_url TEXT,
  bgg_id VARCHAR UNIQUE,
  bgg_url TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
```

### 2.4 Resources
```sql
CREATE TABLE resources (
  id VARCHAR PRIMARY KEY,
  game_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  original_filename TEXT,
  author TEXT,
  attribution_url TEXT,
  url TEXT NOT NULL,
  content TEXT DEFAULT '',
  version INTEGER DEFAULT 0,
  pdf_extractor VARCHAR(50),
  processed_at TIMESTAMPTZ,
  status VARCHAR(50) DEFAULT 'ready',
  current_run_id VARCHAR,
  processing_stage VARCHAR(50),
  processing_metadata JSONB,
  description TEXT,
  resource_type VARCHAR(50) DEFAULT 'rulebook',
  language VARCHAR(10) DEFAULT 'en',
  edition VARCHAR(100),
  is_official BOOLEAN DEFAULT TRUE,
  page_count INTEGER,
  image_count INTEGER DEFAULT 0,
  word_count INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);
```

### 2.5 Attachments
```sql
CREATE TABLE attachments (
  id VARCHAR PRIMARY KEY,
  game_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  resource_id VARCHAR NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
  type VARCHAR(50) DEFAULT 'image',
  mime_type VARCHAR(100) NOT NULL,
  blob_key TEXT NOT NULL,
  url TEXT NOT NULL,
  original_filename TEXT,
  page_number INTEGER,
  bbox JSONB,  -- [x1, y1, x2, y2]
  caption TEXT,
  width INTEGER,
  height INTEGER,
  description TEXT,
  is_good_quality VARCHAR(10),  -- 'good'|'bad'
  is_relevant BOOLEAN,
  detected_type VARCHAR(50),  -- diagram|table|photo|icon|decorative
  ocr_text TEXT,
  created_at TIMESTAMPTZ NOT NULL
);
```

### 2.6 Fragments
```sql
CREATE TABLE fragments (
  id VARCHAR PRIMARY KEY,
  game_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  resource_id VARCHAR NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  embedding vector(1536) NOT NULL,
  version INTEGER DEFAULT 0,
  type VARCHAR(50) DEFAULT 'text',  -- text|image|table
  attachment_id VARCHAR REFERENCES attachments(id) ON DELETE SET NULL,
  searchable_content TEXT,
  synthetic_questions JSONB,  -- ["q1", "q2", ...]
  answer_types JSONB,  -- ["type1", ...]
  resource_name TEXT,
  resource_description TEXT,
  resource_type VARCHAR(50),
  page_number INTEGER,
  page_range JSONB,  -- [start, end]
  section TEXT,
  images JSONB,
  search_vector TSVECTOR,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL
);

-- Indexes
CREATE INDEX ON fragments USING GIN(search_vector);
CREATE INDEX ON fragments USING HNSW(embedding vector_ip_ops);
```

### 2.7 Embeddings (HyDE)
```sql
CREATE TABLE embeddings (
  id VARCHAR PRIMARY KEY,  -- fragmentId or fragmentId-q{0-4}
  fragment_id VARCHAR NOT NULL REFERENCES fragments(id) ON DELETE CASCADE,
  game_id VARCHAR NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  resource_id VARCHAR NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
  type VARCHAR(50) NOT NULL,  -- 'content'|'question'
  embedding vector(1536) NOT NULL,
  question_index INTEGER,  -- 0-4 for questions
  question_text TEXT,
  page_number INTEGER,
  section TEXT,
  fragment_type VARCHAR(50),
  version INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL
);

-- Indexes
CREATE INDEX ON embeddings USING IVFFLAT(embedding vector_ip_ops) WITH (lists=100);
CREATE INDEX ON embeddings USING IVFFLAT(embedding vector_cosine_ops) WITH (lists=100);
```

### 2.8 Workflow Run Records
```sql
CREATE TABLE workflow_run_records (
  id VARCHAR PRIMARY KEY,
  workflow_name VARCHAR NOT NULL,
  status VARCHAR(50) DEFAULT 'pending',
  metadata JSONB DEFAULT '{}',
  resource_id VARCHAR,
  attachment_id VARCHAR,
  game_id VARCHAR,
  external_run_id VARCHAR,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ
);
```

---

## 3. Authentication

### 3.1 Magic Link Flow
1. User submits email → POST /api/auth/login
2. Generate 32-byte hex token, expires in 15 minutes
3. Store in verification_tokens
4. Send email (dev: return in response)
5. User clicks link → POST /api/auth/verify with token
6. Validate token, delete after use
7. Create user if needed (name = email prefix)
8. Generate JWT, return in response

### 3.2 JWT Structure
**Algorithm:** HS256
**Payload:**
```json
{
  "user_id": "string",
  "email": "string",
  "is_admin": "boolean",
  "exp": "30 days from issue"
}
```

### 3.3 Authorization
- Bearer token in Authorization header
- Admin endpoints check `is_admin` claim

---

## 4. PDF Processing Pipeline

### 4.1 Six Stages

**Stage 1: INGEST**
- Extract PDF with Mistral API
- Returns text + images (base64) + page metadata

**Stage 2: VISION** (if images exist)
- Analyze each image with GPT vision
- Generate: description, quality, relevance, OCR text
- Store in attachments table

**Stage 3: CLEANUP**
- Clean markdown with LLM
- Normalize formatting

**Stage 4: METADATA**
- Generate resource name/description
- Extract: page count, word count, language, type

**Stage 5: EMBED**
- Chunk content semantically
- Generate embeddings (OpenAI text-embedding-3-small, 1536 dims)
- Generate synthetic questions (HyDE) - up to 5 per fragment
- Classify answer types
- Store in fragments + embeddings tables

**Stage 6: FINALIZE**
- Mark resource as 'completed'
- Set processed_at timestamp

### 4.2 Error Handling
- If any stage fails: mark resource as 'failed'
- Store error in workflow_run_records
- Can retry from specific stage

---

## 5. RAG System

### 5.1 Hybrid Search

**Three retrieval methods:**
1. **Vector Search (Content)** - fragments.embedding with HNSW
2. **Vector Search (Questions)** - embeddings table type='question'
3. **Full-Text Search** - PostgreSQL tsvector + ts_rank_cd

### 5.2 Reciprocal Rank Fusion (RRF)
Combines rankings: `∑(weight / (k + rank))`
- k = 50
- Content weight = 1.0
- Question weight = 0.7
- FTS weight = 1.0

### 5.3 Answer Type Boosting
- Classify query into answer types
- Boost matching fragments by 1.3x
- Types: player_count, setup_instructions, win_conditions, etc.

### 5.4 LLM Reranking (Optional)
- Model: GPT-4o-mini
- Score each candidate 0-100
- Sort by relevance

### 5.5 Result Diversification
- Max 2 results per page
- Max 6 results per resource
- Default limit: 5 results

### 5.6 HyDE (Hypothetical Document Embeddings)
For each fragment:
1. Generate 1-5 synthetic questions with GPT
2. Embed questions separately
3. Store in embeddings table
4. During search: match queries to synthetic questions

---

## 6. Background Jobs

### 6.1 processResourceWorkflow
**Trigger:** Resource creation
**Stages:** ingest → vision → cleanup → metadata → embed → finalize
**Resumable:** Can restart from specific stage

### 6.2 analyzeImagesWorkflow
**Modes:**
- single-attachment: Reanalyze one attachment
- batch-resource: Analyze all images in resource

---

## 7. File Storage

### 7.1 Storage Paths
```
resources/{resource_id}/source.{ext}           -- Original PDF
resources/{resource_id}/attachments/{id}.{ext} -- Extracted images
games/{timestamp}-{nanoid}.{ext}               -- Game images
uploads/{timestamp}-{nanoid}.{ext}             -- Generic uploads
```

### 7.2 Storage Backend
- Production: Vercel Blob (or S3-compatible)
- Development: Local filesystem (`./uploads/`)

---

## 8. Environment Variables

```bash
# Database
DATABASE_URL=postgres://...
DATABASE_URL_TEST=postgres://...

# OpenAI
OPENAI_API_KEY=sk-...

# Mistral (PDF Extraction)
MISTRAL_API_KEY=...

# Authentication
SESSION_SECRET=...  # Min 32 chars, for JWT signing

# File Storage
BLOB_READ_WRITE_TOKEN=...  # Vercel Blob (optional)

# Redis (Background Jobs + Rate Limiting)
REDIS_URL=redis://...

# Optional
SENTRY_DSN=...
```

---

## 9. Implementation Priority

### Phase 1: Core CRUD
- [x] Users, Games (basic)
- [ ] Games (full CRUD with slug generation)
- [ ] Resources (CRUD, no processing)
- [ ] Attachments (CRUD)

### Phase 2: Authentication
- [x] Magic link flow
- [x] JWT generation/validation
- [ ] Email sending (production)

### Phase 3: PDF Pipeline
- [ ] Mistral PDF extraction
- [ ] Vision image analysis
- [ ] Content cleanup
- [ ] Metadata extraction
- [ ] Embedding generation
- [ ] HyDE question generation

### Phase 4: RAG System
- [ ] Vector search
- [ ] Full-text search
- [ ] RRF fusion
- [ ] Answer type classification
- [ ] LLM reranking
- [ ] Chat streaming

### Phase 5: Background Jobs
- [ ] SAQ worker setup
- [ ] Process resource workflow
- [ ] Analyze images workflow

### Phase 6: File Storage
- [ ] Local filesystem backend
- [ ] Vercel Blob / S3 backend
- [ ] Upload endpoints
