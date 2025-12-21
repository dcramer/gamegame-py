#!/usr/bin/env bash
#
# Bootstrap script for GameGame development environment
#
# Usage:
#   ./scripts/bootstrap.sh
#

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}Setting up GameGame development environment...${NC}"
echo ""

# Check for uv
if ! command -v uv &> /dev/null; then
    if [ -f "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo -e "${YELLOW}Installing uv...${NC}"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi
echo -e "${GREEN}✓ uv available${NC}"

# Install honcho for process management (if overmind not available)
if ! command -v overmind &> /dev/null; then
    echo ""
    echo -e "${CYAN}Installing honcho for process management...${NC}"
    uv tool install honcho 2>/dev/null || pip install --user honcho 2>/dev/null || true
    echo -e "${GREEN}✓ honcho available${NC}"
fi

# Backend setup
echo ""
echo -e "${CYAN}Setting up backend...${NC}"
cd backend
uv sync --all-extras
echo -e "${GREEN}✓ Backend dependencies installed${NC}"

# Install pre-commit hooks
cd ..
echo ""
echo -e "${CYAN}Installing pre-commit hooks...${NC}"
cd backend && uv run pre-commit install --config ../.pre-commit-config.yaml
echo -e "${GREEN}✓ Pre-commit hooks installed${NC}"

# Frontend setup
cd ../frontend
if command -v npm &> /dev/null; then
    echo ""
    echo -e "${CYAN}Setting up frontend...${NC}"
    npm install
    echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
else
    echo ""
    echo -e "${YELLOW}⚠ npm not found, skipping frontend setup${NC}"
fi

echo ""
echo -e "${GREEN}Done! Development environment is ready.${NC}"
echo ""
echo "Next steps:"
echo "  1. Start services:  make up"
echo "  2. Run migrations:  make migrate"
echo "  3. Start dev:       make dev"
echo ""
echo "Access the app at http://localhost:5173"
