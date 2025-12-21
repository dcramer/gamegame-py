# Gap Analysis: Python Backend vs TypeScript Original

## Summary

The Python backend implements approximately **65-70%** of the original TypeScript functionality. Key gaps exist in advanced search features, pipeline sophistication, and some API endpoints.

---

## 1. API Endpoint Gaps

### Missing Endpoints

| Endpoint | Priority | Notes |
|----------|----------|-------|
| `GET /resources/{id}/attachments` | High | List attachments for a resource |
| `GET /games/{id}/attachments` | High | List attachments for a game |
| `GET /bgg/search?query=` | Medium | Search BGG for games |
| `POST /bgg/games/{id}/import` | Medium | Import game from BGG |
| `POST /auth/refresh` | Medium | Refresh JWT token |
| `GET /admin/workflows` | Low | List workflow runs |
| `GET /admin/workflows/{runId}` | Low | Get workflow run details |
| `POST /admin/workflows/{runId}/retry` | Low | Retry failed workflow |

### Response Schema Differences

| Issue | Impact |
|-------|--------|
| ID type: `int` vs `string` (nanoid) | High - API contract mismatch |
| Timestamps: `datetime` vs `bigint` (ms) | Medium - Client parsing |
| Field naming: `snake_case` vs `camelCase` | High - API contract |
| Missing `resource_type` in ResourceRead | Low |

---

## 2. Database Schema Gaps

### Critical Differences

| Table | Issue | Impact |
|-------|-------|--------|
| All tables | `int` IDs vs `nanoid` strings | High |
| All tables | `datetime` vs `bigint` timestamps | Medium |
| Fragments | Missing `version` column | High - No reindex tracking |
| Fragments | Missing `searchable_content` column | High - Search quality |
| Fragments | Missing `answer_types` column | Medium - Search filtering |
| Fragments | Missing `page_range` column | Low |
| Fragments | Wrong vector operator (cosine vs inner product) | High - Retrieval quality |
| Attachments | Missing `width`, `height` columns | Low |
| Attachments | Missing `caption`, `is_relevant` columns | Medium |
| Resources | Missing `author`, `attribution_url` columns | Low |
| Resources | Missing `language`, `edition`, `is_official` columns | Low |

### Index Gaps

| Missing Index | Impact |
|---------------|--------|
| `fragments_game_id_idx` | Query performance |
| `fragments_resource_id_idx` | Query performance |
| `embeddings_game_id_idx` | Query performance |
| HNSW on embeddings table | Vector search performance |

---

## 3. Search Service Gaps

### Missing Features (High Priority)

| Feature | Description | Impact |
|---------|-------------|--------|
| LLM Reranking | Cross-encoder scoring after initial retrieval | Major - Answer quality |
| Answer Type Classification | `rules`, `setup`, `component`, etc. | Major - Search precision |
| Searchable Content | Enriched text with context for embedding | Major - Retrieval quality |
| Resource Type Filtering | Filter by rulebook/FAQ/errata in search | Medium |
| Offset Pagination | `offset` param in search | Low |

### Implementation Differences

| Area | Python | TypeScript | Impact |
|------|--------|------------|--------|
| RRF weights | `vector:0.5, hyde:0.35, fts:0.15` | `vector:0.5, hyde:0.35, fts:0.15` | Match |
| RRF k parameter | 50 | 50 | Match |
| Per-resource limit | 3 | 3 | Match |
| Query answer type | Not implemented | Classified before search | High |
| Score threshold | Not implemented | 0.01 minimum | Low |

---

## 4. Chat Service Gaps

### Tool Differences

| Tool | Python | TypeScript | Gap |
|------|--------|------------|-----|
| `search_resources` | Basic | Has `resource_type` filter | Medium |
| `search_images` | Keyword matching | Has `image_type` filter, semantic | High |
| `get_attachment` | Present | Present | - |
| `list_resources` | Present | Present | - |

### System Prompt

The Python prompt is simpler. Missing from Python:
- Expansion-specific guidance
- Player count variation emphasis
- Response formatting examples

---

## 5. Pipeline Gaps

### Stage-by-Stage Comparison

| Stage | Python | TypeScript | Gap Severity |
|-------|--------|------------|--------------|
| **INGEST** | Mistral OCR, state in DB | Mistral OCR, blob storage | Low |
| **VISION** | GPT-4o batch | GPT-4o batch with context | Low |
| **CLEANUP** | LLM per-chunk | LLM per-page batch | Low |
| **METADATA** | Local calculation | LLM name/description | **High** |
| **EMBED** | Basic chunking | Structured PDF chunking | **High** |

### Critical Embed Stage Gaps

| Feature | Impact |
|---------|--------|
| No structured PDF chunking (page/section aware) | High |
| No answer type classification | High |
| No searchable content enrichment | High |
| No image fragments | Medium |
| No version tracking | Medium |
| No idempotent image handling | Medium |
| No orphan cleanup | Low |
| HyDE: 3 questions vs 5 | Low |

### Missing Pipeline Features

1. **Workflow Run Tracking** - No `recordWorkflowStage` equivalent
2. **Progress Reporting** - No intermediate status updates
3. **Blob-based State** - No structured JSON persistence
4. **Idempotent Reprocessing** - No smart resume from stage

---

## 6. Priority Recommendations

### P0 - Critical (Required for Feature Parity)

1. **Fix vector operator** - Change from cosine to inner product for OpenAI embeddings
2. **Add reranking** - Implement LLM cross-encoder reranking in search
3. **Add searchable_content** - Enrich embedded text with context
4. **Structured chunking** - Page/section-aware chunking in embed stage
5. **LLM metadata** - Generate name/description in metadata stage

### P1 - High (Significant Quality Impact)

1. **Answer type classification** - Add to both embed and search
2. **Attachment list endpoints** - Add missing API routes
3. **Image semantic search** - Replace keyword matching
4. **Add missing indexes** - Query performance
5. **Fragment version tracking** - Enable reindexing

### P2 - Medium (Nice to Have)

1. **BGG import endpoint** - Full BGG integration
2. **Auth refresh** - Token refresh flow
3. **Image dimensions** - Store width/height
4. **Workflow admin API** - Pipeline monitoring
5. **camelCase responses** - API contract alignment

### P3 - Low (Can Defer)

1. **nanoid IDs** - ID format change
2. **bigint timestamps** - Timestamp format
3. **Resource metadata fields** - author, edition, etc.
4. **Blob cleanup workflow** - Storage maintenance

---

## 7. Estimated Effort

| Priority | Items | Effort |
|----------|-------|--------|
| P0 | 5 | 2-3 days |
| P1 | 5 | 2-3 days |
| P2 | 5 | 2-3 days |
| P3 | 4 | 1-2 days |

**Total estimated effort: 7-11 days** for full parity

---

## 8. Files to Modify

### For P0 Items

- `src/gamegame/models/fragment.py` - Add columns, fix operator
- `src/gamegame/services/search.py` - Add reranking
- `src/gamegame/services/pipeline/embed.py` - Structured chunking
- `src/gamegame/services/pipeline/metadata.py` - LLM generation
- `alembic/versions/` - New migration for schema changes

### For P1 Items

- `src/gamegame/api/attachments.py` - New endpoints
- `src/gamegame/services/chat.py` - Enhanced search_images
- `src/gamegame/services/pipeline/embed.py` - Answer type classification
