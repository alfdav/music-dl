#!/usr/bin/env bash
# Figma MCP preflight check — run BEFORE any Figma MCP session
# Prevents wasted API calls by checking known blockers upfront
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=== Figma MCP Preflight ==="
echo ""

# 1. Check routing type — hash routing breaks generate_figma_design capture
echo -n "Checking frontend routing type... "
if grep -q 'location\.hash\|hashchange\|window\.addEventListener.*hashchange' TIDALDL-PY/tidal_dl/gui/static/app.js 2>/dev/null; then
    echo -e "${RED}HASH-BASED ROUTING DETECTED${NC}"
    echo "  → generate_figma_design (capture) WILL NOT WORK"
    echo "  → The capture script puts params in location.hash"
    echo "  → Your app's router will consume them → 404"
    echo "  → USE ONLY: use_figma (direct frame building)"
    echo ""
    ROUTING="hash"
else
    echo -e "${GREEN}No hash routing detected${NC}"
    echo "  → generate_figma_design capture should work"
    ROUTING="standard"
fi

# 2. Check if capture script is accidentally left in HTML
echo -n "Checking for leftover capture scripts... "
if grep -q 'mcp.figma.com.*capture' TIDALDL-PY/tidal_dl/gui/static/index.html 2>/dev/null; then
    echo -e "${RED}FOUND — remove before committing${NC}"
    echo "  → <script src=\"https://mcp.figma.com/mcp/html-to-design/capture.js\">"
else
    echo -e "${GREEN}Clean${NC}"
fi

# 3. Estimate call budget
echo ""
echo "=== Call Budget Planner ==="
echo "Starter plan: ~15-20 use_figma calls per window"
echo ""
echo "Required calls per screen:"
echo "  whoami:           1 (only first time)"
echo "  create_file:      1 (only if new file)"
echo "  create_variables: 2-3 (colors, spacing, radii)"
echo "  per screen:       3-5 (wrapper + sections + validate)"
echo ""
echo "Estimated for full app (10 screens):"
echo "  Setup:    4 calls"
echo "  Screens: 40 calls (4 avg × 10)"
echo "  Total:   ~44 calls"
echo ""

if [ "$ROUTING" = "hash" ]; then
    echo -e "${YELLOW}DECISION: Skip generate_figma_design entirely.${NC}"
    echo "Go straight to: whoami → create_file → variables → use_figma frames"
else
    echo "generate_figma_design is safe to use for page capture."
fi

echo ""
echo "=== Checklist ==="
echo "[ ] Run whoami to confirm plan tier and key"
echo "[ ] Check plan page limit (Starter=3, Pro=unlimited)"
echo "[ ] Calculate total calls needed vs budget"
echo "[ ] If Starter: batch sections, minimize validate calls"
echo "[ ] NEVER poll generate_figma_design more than 2x before investigating"
echo "[ ] NEVER blame the plan for your wasted calls"
