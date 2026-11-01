# agent-plugins

**English** | [中文](README_CN.md)

One repository for Claude Code plugins and the MCP services they share.

```
agent-plugins (marketplace: agent-plugins)
│
├── domain plugin ──────── pcb-design
│        │ dependencies
│        ▼
└── konnect (MCP plugin) ──► external `konnect` executable (KiCad)
```

- **Domain plugins** (`pcb-design`): each contains only its own Skills, Agents and Hooks.
- **konnect**: shared MCP for KiCad schematic/PCB design. The server is the external
  [Konnect](https://github.com/mixelpixx/Konnect) binary; this repository only registers it (`mcp/konnect/plugin/`).
  Domain plugins use it through Claude Code's official plugin `dependencies` mechanism.
- Design rationale: [docs/architecture.md](docs/architecture.md); day-to-day development: [docs/development.md](docs/development.md).

## Plugins

| Plugin | Purpose |
|---|---|
| `pcb-design` | KiCad schematic organisation, PCB board definition and sub-module placement |
| `konnect` | Shared MCP registering the Konnect KiCad tools; installed automatically as a dependency |

`pcb-design` declares `"dependencies": ["konnect"]`. Its skills:

| Skill | Purpose |
|---|---|
| `sch_organize` | Split each schematic sheet into independent sub-modules and divide the page into named regions |
| `pcb_board_info` | Apply a JSON board spec: outline (rectangle/circle), mounting holes, stackup, edge clearance |
| `pcb_submodule_placement` | Place one schematic sub-module on the PCB (decoupling, filter capacitors, silkscreen) |

## Layout

```
agent-plugins/
├── .claude-plugin/marketplace.json   # marketplace "agent-plugins": lists every plugin
├── plugins/                          # domain plugins (one per domain)
│   └── pcb-design/   {.claude-plugin/plugin.json, skills/, agents/, hooks/}
├── mcp/                              # shared MCP servers (one per capability)
│   └── konnect/                      # external MCP: only the registering plugin (.mcp.json command: konnect)
├── tools/{plugin-install.sh, validate.sh}
├── tests/                            # repository architecture rules
└── docs/
```

## Prerequisites

- [uv](https://docs.astral.sh/uv/) and `claude` (the Claude Code CLI)
- For `pcb-design`: KiCad (with `kicad-cli`) and the [Konnect](https://github.com/mixelpixx/Konnect) plugin, its
  `konnect` executable on PATH (e.g. `ln -s <konnect>/plugins/bin/konnect ~/.local/bin/konnect`).

## Quick start: choose plugins per project

Plugins are not installed globally. They are **enabled per project directory**: Claude Code only loads the
plugins chosen for the directory it is opened in.

One-time setup (the only time the full path is needed):

```bash
/home/agent/Projects/tools/agent-plugins/tools/plugin-install.sh --setup
```

This checks the MCP executables, registers the marketplace and links `plugin-install.sh` into
`~/.local/bin`, so from then on it works from any directory. (Running it with a plugin name the first
time also performs the setup automatically.)

Then, for each project:

```bash
cd ~/work/my-board
plugin-install.sh pcb-design      # PCB design only in this directory
claude
```

More:

```bash
plugin-install.sh -C ~/work/other pcb-design         # -C picks the project directory; several plugins allowed
plugin-install.sh --remove pcb-design                # disable for the current directory
plugin-install.sh                                    # list available plugins and usage
plugin-install.sh --setup                            # re-run after changing MCP code
tools/validate.sh                                    # validate the repository
```

Result:

| Directory Claude Code is opened in | Plugins loaded | konnect MCP |
|---|---|---|
| `~/work/my-board` | pcb-design + konnect | ✔ |
| any other directory | none | not started |

### Where the choice is recorded (`-s/--scope`)

| scope | written to | applies to |
|---|---|---|
| `local` (default) | `<project>/.claude/settings.local.json` | only you, only this project |
| `project` | `<project>/.claude/settings.json` | everyone using the project, once committed to git |
| `user` | `~/.claude/settings.json` | all your projects (global; usually not wanted) |

For example, `local` writes:

```json
{
  "enabledPlugins": { "pcb-design@agent-plugins": true, "konnect@agent-plugins": true },
  "permissions": { "allow": ["Read(//home/agent/Projects/tools/agent-plugins/**)"] }
}
```

`konnect` is pulled into the same scope through `dependencies`; `--remove` also removes it when no other
plugin there still needs it.

The `Read` rule lets Claude read the plugin files (shared `scripts/` and `references/` used by skills) without a
permission prompt: they live in this repository, outside the project directory. It is added when a plugin is
enabled and removed by `--remove` once no plugin from this repository is enabled in that settings file any more;
other settings in the file are left untouched.

### What plugin-install.sh does (can also be run by hand)

Setup (once, or with `--setup`):

1. **Checks the MCP executables**: MCP servers built in this repository (`mcp/<name>/pyproject.toml`) are installed
   with `uv tool install --reinstall`; external ones such as `konnect` are only checked and a warning is printed
   when they are not on PATH.
2. **Registers the marketplace**: `claude plugin marketplace add /home/agent/Projects/tools/agent-plugins`.
   A marketplace is only a catalog; registering it does not enable any plugin in any project.
3. **Links the script**: `~/.local/bin/plugin-install.sh -> /home/agent/Projects/tools/agent-plugins/tools/plugin-install.sh`.

Every run with plugin names (about one second):

4. **Enables plugins in the chosen project**:

   ```bash
   cd <project> && claude plugin install --scope local pcb-design@agent-plugins
   cd <project> && claude plugin uninstall --scope local --prune pcb-design@agent-plugins   # disable
   ```

### Loading plugins for one session only

Scopes work per **directory**. To try a plugin without installing anything, load it at startup instead (this
affects only that session and writes no configuration):

```bash
R=/home/agent/Projects/tools/agent-plugins
claude --plugin-dir $R/plugins/pcb-design --plugin-dir $R/mcp/konnect/plugin
```

`--plugin-dir` bypasses the marketplace, so the MCP plugin directory has to be passed as well: a plugin whose
dependency is missing is silently not loaded (no skills, no error).

## Verification

### Verify the plugins

```bash
claude plugin validate --strict .                    # marketplace
claude plugin validate --strict plugins/pcb-design
claude plugin validate --strict mcp/konnect/plugin
claude plugin list                                   # run in a project directory: chosen plugins are enabled
python3 -m unittest discover -s tests -t . -v        # repository architecture rules
```

### Verify the MCP

```bash
cd <project> && claude mcp list                      # run in a project directory with a plugin enabled
# plugin:konnect:konnect: konnect  - ✔ Connected
```

In a session, `/mcp` lists `plugin:konnect:konnect`; its tools are named `mcp__plugin_konnect_konnect__<tool>`.

## Extending

- New domain: `plugins/<name>/`, added to `marketplace.json`.
- New shared capability: `mcp/<name>/` (with a `plugin/` wrapper), added to `marketplace.json`; plugins
  that need it declare it in `dependencies`.
- See [docs/development.md](docs/development.md).
