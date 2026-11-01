#!/usr/bin/env bash
# Enable selected plugins from this repository for one project (not globally).
#
#   cd ~/work/my-board
#   plugin-install.sh pcb-design              # enable pcb-design for the current directory, then run `claude`
#   plugin-install.sh -C ~/work/other pcb-design  # enable it for another project
#   plugin-install.sh -s project pcb-design   # shared with the team via .claude/settings.json
#   plugin-install.sh --remove pcb-design     # disable it again for the current directory
#   plugin-install.sh                     # list the available plugins
#   plugin-install.sh --setup             # (re)install the shared parts; also run after MCP code changes
#
# Scopes (where the choice is recorded):
#   local   (default) <project>/.claude/settings.local.json  only you, only this project
#   project           <project>/.claude/settings.json        everyone using this project
#   user              ~/.claude/settings.json                every project (global)
#
# Setup (done automatically on first use, or explicitly with --setup) installs the MCP
# executables, registers the marketplace and links this script into uv's bin directory
# (~/.local/bin) so that `plugin-install.sh` works from any directory.
# Shared MCP plugins (e.g. konnect) come in automatically through each plugin's
# "dependencies", in the same scope, and are removed again with --remove.
# Enabling also allows reading this repository (skills read their shared scripts/ and
# references/ from it) in the same settings file; --remove drops that rule once no plugin
# from this repository is enabled there any more.
set -euo pipefail

SELF="$(readlink -f "${BASH_SOURCE[0]}")"
REPO="$(cd "$(dirname "$SELF")/.." && pwd)"
MARKETPLACE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$REPO/.claude-plugin/marketplace.json")"
LINK_NAME="plugin-install.sh"

usage() { sed -n '2,25s/^# \{0,1\}//p' "$SELF"; }

available() {
    for manifest in "$REPO"/plugins/*/.claude-plugin/plugin.json; do
        python3 -c '
import json, sys
m = json.load(open(sys.argv[1]))
print("  %-14s %s" % (m["name"], m.get("description", "")))' "$manifest"
    done
}

need() { command -v "$1" >/dev/null || { echo "error: '$1' not found on PATH" >&2; exit 1; }; }

mcp_dirs() {
    for wrapper in "$REPO"/mcp/*/plugin/.claude-plugin/plugin.json; do
        echo "${wrapper%/plugin/.claude-plugin/plugin.json}"
    done
}

mcp_executables() {
    for dir in $(mcp_dirs); do
        [ -f "$dir/pyproject.toml" ] || continue
        python3 -c '
import sys, tomllib
print(*tomllib.load(open(sys.argv[1], "rb"))["project"].get("scripts", {}))' "$dir/pyproject.toml"
    done
}

# MCP servers this repository only registers (no pyproject): their executables are installed externally.
external_mcp_executables() {
    for dir in $(mcp_dirs); do
        [ -f "$dir/pyproject.toml" ] && continue
        python3 -c '
import json, sys
print(*(s["command"] for s in json.load(open(sys.argv[1]))["mcpServers"].values()))' "$dir/plugin/.mcp.json"
    done
}

marketplace_registered() {
    claude plugin marketplace list --json 2>/dev/null | python3 -c '
import json, sys
sys.exit(0 if any(m.get("name") == sys.argv[1] for m in json.load(sys.stdin)) else 1)' "$MARKETPLACE"
}

setup_complete() {
    for exe in $(mcp_executables); do command -v "$exe" >/dev/null || return 1; done
    [ "$(readlink -f "$(uv tool dir --bin)/$LINK_NAME" 2>/dev/null)" = "$SELF" ] || return 1
    marketplace_registered
}

setup() {
    # The MCP executables are plain commands on PATH; they only run in projects where a plugin needs them.
    echo "==> Installing MCP executables (uv tool install)"
    for dir in $(mcp_dirs); do
        [ -f "$dir/pyproject.toml" ] || continue
        echo "  - ${dir#"$REPO"/}"
        uv tool install --quiet --reinstall "$dir"
    done
    for exe in $(external_mcp_executables); do
        command -v "$exe" >/dev/null || echo "warning: external MCP executable '$exe' not on PATH (see mcp/*/README.md)" >&2
    done

    # A marketplace is only a catalog: registering it does not enable any plugin anywhere.
    echo "==> Registering marketplace '$MARKETPLACE' ($REPO)"
    claude plugin marketplace add "$REPO"

    local bin
    bin="$(uv tool dir --bin)"
    echo "==> Linking $bin/$LINK_NAME -> $SELF"
    ln -sfn "$SELF" "$bin/$LINK_NAME"
    case ":$PATH:" in
        *":$bin:"*) ;;
        *) echo "warning: $bin is not on PATH; add it to use '$LINK_NAME' from any directory" >&2 ;;
    esac
}

settings_file() {
    case "$SCOPE" in
        local)   echo "$PROJECT/.claude/settings.local.json" ;;
        project) echo "$PROJECT/.claude/settings.json" ;;
        user)    echo "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json" ;;
    esac
}

# Plugin files live outside the project, so reading a skill's scripts/references would otherwise
# prompt for permission. `add` allows reading the repository; `remove` drops the rule again unless
# another plugin from this marketplace is still enabled in the same settings file.
read_permission() {
    python3 - "$1" "$(settings_file)" "Read(/$REPO/**)" "@$MARKETPLACE" <<'EOF'
import json, os, sys
action, path, rule, suffix = sys.argv[1:]
data = json.load(open(path)) if os.path.exists(path) else {}
allow = data.setdefault("permissions", {}).setdefault("allow", [])
if action == "add":
    if rule in allow:
        sys.exit()
    allow.append(rule)
    print(f"==> Allowing {rule} in {path}")
else:
    still_enabled = any(k.endswith(suffix) and v for k, v in data.get("enabledPlugins", {}).items())
    if still_enabled or rule not in allow:
        sys.exit()
    allow.remove(rule)
    if not allow:
        del data["permissions"]["allow"]
    if not data["permissions"]:
        del data["permissions"]
    print(f"==> Removing {rule} from {path}")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
EOF
}

SCOPE=local
PROJECT="$PWD"
REMOVE=0
SETUP=0
plugins=()
while [ $# -gt 0 ]; do
    case "$1" in
        -s|--scope)   SCOPE="$2"; shift 2 ;;
        -C|--project) PROJECT="$2"; shift 2 ;;
        --remove)     REMOVE=1; shift ;;
        --setup)      SETUP=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        -*)           echo "error: unknown option $1" >&2; exit 2 ;;
        *)            plugins+=("$1"); shift ;;
    esac
done
case "$SCOPE" in local|project|user) ;; *) echo "error: --scope must be local, project or user" >&2; exit 2 ;; esac

for plugin in "${plugins[@]}"; do
    if [ ! -f "$REPO/plugins/$plugin/.claude-plugin/plugin.json" ]; then
        echo "error: unknown plugin '$plugin'. Available plugins:" >&2
        available >&2
        exit 2
    fi
done

need claude
need uv

if [ "$SETUP" -eq 1 ]; then
    setup
elif [ ${#plugins[@]} -eq 0 ]; then
    usage
    echo
    echo "Available plugins:"
    available
    exit 0
elif [ "$REMOVE" -eq 0 ] && ! setup_complete; then
    echo "==> First use: running setup"
    setup
fi

[ ${#plugins[@]} -eq 0 ] && exit 0
PROJECT="$(cd "$PROJECT" && pwd)"

if [ "$REMOVE" -eq 1 ]; then
    echo "==> Disabling (scope: $SCOPE, project: $PROJECT): ${plugins[*]}"
    for plugin in "${plugins[@]}"; do
        # --prune also drops dependencies (konnect) that no remaining plugin in this scope needs.
        (cd "$PROJECT" && claude plugin uninstall --scope "$SCOPE" --prune -y "$plugin@$MARKETPLACE")
    done
    read_permission remove
    exit 0
fi

echo "==> Enabling (scope: $SCOPE, project: $PROJECT): ${plugins[*]}"
for plugin in "${plugins[@]}"; do
    (cd "$PROJECT" && claude plugin install --scope "$SCOPE" "$plugin@$MARKETPLACE")
done
read_permission add

echo
echo "Done. Run 'claude' in $PROJECT (or /reload-plugins in an open session there)."
