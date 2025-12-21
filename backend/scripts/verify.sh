#!/usr/bin/env bash
#
# Automated verification script for the GameGame backend
# Run this to verify the codebase is in a good state
#
# Usage:
#   ./scripts/verify.sh          # Run all checks
#   ./scripts/verify.sh --quick  # Skip tests (lint + type check only)
#   ./scripts/verify.sh --ci     # CI mode (includes test coverage)
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse arguments
QUICK=false
CI=false
for arg in "$@"; do
    case $arg in
        --quick)
            QUICK=true
            ;;
        --ci)
            CI=true
            ;;
    esac
done

# Track failures
FAILED=0

echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  GameGame Backend Verification${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# Step 1: Check uv is available
echo -e "${YELLOW}[1/5] Checking uv is installed...${NC}"
if ! command -v uv &> /dev/null; then
    # Try common locations
    if [ -f "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    elif [ -f "$HOME/.cargo/bin/uv" ]; then
        export PATH="$HOME/.cargo/bin:$PATH"
    else
        echo -e "${RED}✗ uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✓ uv is available${NC}"
echo ""

# Step 2: Sync dependencies
echo -e "${YELLOW}[2/5] Installing/syncing dependencies...${NC}"
if uv sync --all-extras --quiet 2>/dev/null; then
    echo -e "${GREEN}✓ Dependencies synced${NC}"
else
    echo -e "${RED}✗ Failed to sync dependencies${NC}"
    FAILED=1
fi
echo ""

# Step 3: Run linter
echo -e "${YELLOW}[3/5] Running linter (ruff)...${NC}"
if uv run ruff check . 2>/dev/null; then
    echo -e "${GREEN}✓ Linting passed${NC}"
else
    echo -e "${RED}✗ Linting failed${NC}"
    FAILED=1
fi
echo ""

# Step 4: Run type checker
echo -e "${YELLOW}[4/5] Running type checker (ty)...${NC}"
if uvx ty check 2>/dev/null; then
    echo -e "${GREEN}✓ Type checking passed${NC}"
else
    echo -e "${RED}✗ Type checking failed${NC}"
    FAILED=1
fi
echo ""

# Step 5: Run tests (unless --quick)
if [ "$QUICK" = true ]; then
    echo -e "${YELLOW}[5/5] Skipping tests (--quick mode)${NC}"
else
    echo -e "${YELLOW}[5/5] Running tests...${NC}"

    # Check if database is available
    if command -v docker &> /dev/null && docker compose ps 2>/dev/null | grep -q "postgres.*Up"; then
        if [ "$CI" = true ]; then
            if uv run pytest --cov=gamegame --cov-report=term-missing --cov-report=xml 2>/dev/null; then
                echo -e "${GREEN}✓ Tests passed with coverage${NC}"
            else
                echo -e "${RED}✗ Tests failed${NC}"
                FAILED=1
            fi
        else
            if uv run pytest 2>/dev/null; then
                echo -e "${GREEN}✓ Tests passed${NC}"
            else
                echo -e "${RED}✗ Tests failed${NC}"
                FAILED=1
            fi
        fi
    else
        echo -e "${YELLOW}⚠ Database not available, skipping tests${NC}"
        echo -e "${YELLOW}  Start with: docker compose up -d${NC}"
    fi
fi
echo ""

# Summary
echo -e "${CYAN}============================================${NC}"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}  All checks passed!${NC}"
    echo -e "${CYAN}============================================${NC}"
    exit 0
else
    echo -e "${RED}  Some checks failed${NC}"
    echo -e "${CYAN}============================================${NC}"
    exit 1
fi
