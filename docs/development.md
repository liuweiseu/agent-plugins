# Development

## 开发循环

marketplace 是本地目录时，plugin **原地加载**（不拷贝），修改 Skill / Agent / Hook 后：

- 新会话自动生效，或在当前会话执行 `/reload-plugins`。
- 本仓库实现的 MCP 源码修改后需要重装可执行文件：`plugin-install.sh --setup`（或 `uv tool install --reinstall ./mcp/<name>`），
  然后 `/reload-plugins`。外部 MCP（如 `konnect`）按其自身方式升级。

`README.md`（英文）和 `README_CN.md`（中文翻译）必须同步修改：改其中一份时同时更新另一份，保持章节结构一致。

提交前运行：

```bash
tools/validate.sh           # manifests (--strict) + 架构规则 + MCP 测试
tools/validate.sh --quick   # 跳过 MCP 测试
```

## 添加 Skill

```
plugins/<domain>/skills/<skill-name>/
├── SKILL.md            # 必需
├── scripts/            # 可选：该 Skill 私有的辅助程序
└── references/         # 可选：按需读取的参考资料
```

```markdown
---
name: board-check
description: Check a KiCad board against the fab house rules and report the problems. Use when ...
---

1. Load the Konnect `verification` toolset and run DRC on the board ...
2. Run `${CLAUDE_PLUGIN_ROOT}/skills/board-check/scripts/summarise.py` on the report ...
```

- `description` 决定 Claude 何时自动使用该 Skill，写清楚触发场景。
- KiCad 项目一律通过 Konnect MCP tool 修改；只有 Konnect 做不到的事才由 Skill 的 `scripts/` 处理文件，并用 `kicad-cli` 验证。
- Skill 内引用自身文件时用 `${CLAUDE_PLUGIN_ROOT}`，不要写绝对路径。

## 添加 Subagent

`plugins/<domain>/agents/<name>.md`：

```markdown
---
name: board-reviewer
description: Reviews a KiCad board end to end (schematic, layout, DRC) and returns a list of findings. Use when ...
tools: Read, Grep, Glob, Bash, mcp__plugin_konnect_konnect
---

You are ...
```

只有当任务需要独立 context、能整体委托并只返回结论时才创建 Subagent。

## 添加 Hook

`plugins/<domain>/hooks/hooks.json`（文件内容以 `"hooks"` 为顶层 key）：

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/hooks/check-env.sh" }] }
    ]
  }
}
```

## 添加领域 Plugin

1. 复制 `plugins/pcb-design/` 的结构（`.claude-plugin/plugin.json`、`skills/`、`agents/`、`hooks/`）到 `plugins/<name>/`，
   修改 `.claude-plugin/plugin.json` 的 `name` / `description`。
2. 需要公共 MCP 时在 `dependencies` 中列出（如 `["konnect"]`）。
3. 在 `.claude-plugin/marketplace.json` 的 `plugins` 中加一项 `{"name": "<name>", "source": "./plugins/<name>"}`。
4. `tools/validate.sh`。

## 添加公共 MCP

本仓库实现的 MCP：

1. `mcp/<name>/`：`pyproject.toml`（`[project.scripts]` 提供可执行文件）、`src/`、`tests/`。
   复用已有的库/客户端，MCP 只做 Agent-facing adapter。
2. `mcp/<name>/plugin/.claude-plugin/plugin.json`（`name` 为 `<name>`）和 `mcp/<name>/plugin/.mcp.json`
   （`command` 为上面的可执行文件名）。
3. 在 `marketplace.json` 中登记 `{"name": "<name>", "source": "./mcp/<name>/plugin"}`，
   需要它的领域 plugin 加入 `dependencies`。
4. `tools/plugin-install.sh` 和 `tools/validate.sh` 会自动发现带 `plugin/` 包装的 `mcp/*/`。
5. 运行 `plugin-install.sh --setup` 安装新的 MCP 可执行文件，再在需要的项目中 `plugin-install.sh <plugin>`。

外部 MCP（服务端不在本仓库，如 `konnect`）：只建 `mcp/<name>/plugin/`（`.mcp.json` 的 `command` 为 PATH 上的可执行文件名，
不写绝对路径）和 `mcp/<name>/README.md` 说明如何安装，不需要 `pyproject.toml`。`plugin-install.sh --setup` 不安装它，
只在可执行文件不在 PATH 上时给出警告。

## 版本

`plugin.json` 中写了 `version`，通过 git 远端分发后，用户只有在版本号变化时才会收到更新，
因此发布 plugin 改动时记得提升对应 plugin 的 `version`。
