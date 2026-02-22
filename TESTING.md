# Testing Playbook

This document covers manual testing workflows for GameGame.

## Chat Testing & Improvement

### Quick Testing with CLI

Use the `ask` command to test chat responses:

```bash
# Single question
mise cli ask scythe-2016 "How do I set up the game?"

# Interactive mode (multiple questions in a session)
mise cli ask scythe-2016

# Verbose mode - shows tool calls, search results, timing
mise cli ask scythe-2016 -v "What happens when I move into a hex with an opponent?"
```

### What to Evaluate

When testing chat responses, assess:

1. **Accuracy**: Is the answer factually correct per the rulebook?
2. **Completeness**: Does it cover all relevant aspects of the question?
3. **Citations**: Are sources properly referenced?
4. **Search Quality**: Did it find the right fragments? (use `-v` to inspect)
5. **Follow-ups**: Are suggested follow-up questions relevant and useful?
6. **Tone**: Is the response helpful without being verbose?

### Key Files for Improvements

| Area | File | Purpose |
|------|------|---------|
| System prompt | `backend/src/gamegame/ai/prompts.py` | LLM instructions and personality |
| Tool definitions | `backend/src/gamegame/ai/tools.py` | Search and attachment tools |
| Hybrid search | `backend/src/gamegame/ai/search.py` | RRF fusion, ranking logic |
| Embeddings | `backend/src/gamegame/ai/embeddings.py` | Embedding generation |
| Chunking | `backend/src/gamegame/utils/chunking.py` | How documents are split |
| Chat endpoint | `backend/src/gamegame/api/chat.py` | Request handling, streaming |

### Common Improvement Areas

**Poor search results?**
- Check chunking strategy in `utils/chunking.py`
- Tune RRF parameters (k value) in `ai/search.py`
- Review HyDE question generation in embedding pipeline

**Wrong tone or format?**
- Adjust system prompt in `ai/prompts.py`
- Modify response schema constraints

**Missing context?**
- Increase `limit` parameter in search tools
- Check if relevant content exists in the resource

**Tool usage issues?**
- Review tool descriptions in `ai/tools.py`
- Check tool call patterns with `-v` flag

### Iteration Workflow

1. Identify issue with `mise cli ask <game> -v "<question>"`
2. Determine root cause (search, prompt, chunking, etc.)
3. Make targeted change to relevant file
4. Re-test same question to verify improvement
5. Test related questions to check for regressions

## Lightweight Eval Harness

A simple deterministic eval runner is available for repeatable checks:

```bash
# List cases
mise cli evals list

# Run suite against a specific game slug/id
mise cli evals run --game scythe-2016

# Run against a non-default API URL
mise cli evals run --game scythe-2016 --url http://localhost:8000
```

Suite file: `backend/evals/cases/boardgame_smoke.json`

Each case supports:
- `must_include`: required phrases in the answer
- `must_not_include`: forbidden phrases
- `min_citations`: minimum required citation count

## QA Examples

### Scythe

See [docs/scythe-example.md](./docs/scythe-example.md) for a complete QA test suite with:
- 5 test questions (simple → complex)
- Expected answers with evaluation checklists
- Scoring guide

## Frontend Smoke Tests

Playwright smoke tests are available for basic route render checks:

```bash
npm --prefix frontend run test:e2e
```
