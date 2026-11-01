#!/usr/bin/env bash
# Validate the repository: manifests, repository layout rules and MCP server tests.
#
#   tools/validate.sh            # everything
#   tools/validate.sh --quick    # skip MCP test suites
#
# Exits non-zero on the first failing step.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

step() { printf '\n==> %s\n' "$*"; }

step "Repository layout"
python3 -m unittest discover -s "$REPO/tests" -t "$REPO" -v 2>&1 | sed 's/^/  /'
test "${PIPESTATUS[0]}" -eq 0

if command -v claude >/dev/null; then
    step "Marketplace manifest"
    claude plugin validate --strict "$REPO"

    # Every plugin listed in the marketplace, including MCP wrapper plugins such as konnect.
    while IFS= read -r source; do
        step "Plugin ${source#./}"
        claude plugin validate --strict "$REPO/$source"
    done < <(python3 -c '
import json, sys
for p in json.load(open(sys.argv[1]))["plugins"]:
    print(p["source"])' "$REPO/.claude-plugin/marketplace.json")
else
    step "Skipping 'claude plugin validate' (claude not on PATH)"
fi

if [ "$QUICK" -eq 0 ]; then
    for wrapper in "$REPO"/mcp/*/plugin/.claude-plugin/plugin.json; do
        dir="${wrapper%/plugin/.claude-plugin/plugin.json}"
        [ -f "$dir/pyproject.toml" ] || continue   # external MCP (e.g. konnect): nothing to test here
        step "MCP tests: ${dir#"$REPO"/}"
        uv run --project "$dir" --directory "$dir" pytest -q
    done
fi

step "MCP executables on PATH"
for wrapper in "$REPO"/mcp/*/plugin/.claude-plugin/plugin.json; do
    # Commands registered in the wrapper's .mcp.json, whether installed by uv or externally.
    for exe in $(python3 -c '
import json, sys
print(*(s["command"] for s in json.load(open(sys.argv[1]))["mcpServers"].values()))' "${wrapper%/.claude-plugin/plugin.json}/.mcp.json"); do
        if command -v "$exe" >/dev/null; then
            echo "  ok      $exe -> $(command -v "$exe")"
        else
            echo "  missing $exe (run tools/plugin-install.sh --setup)"
        fi
    done
done

printf '\nAll checks passed.\n'
