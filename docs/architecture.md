# Architecture

本文记录本仓库采用的结构，以及选择它的理由。

## 职责划分

| 组件 | 角色 | 本仓库中的位置 |
|------|------|----------------|
| Skill | HOW：workflow、instructions、领域知识 | `plugins/<domain>/skills/<skill>/SKILL.md` |
| Skill scripts | 某个 Skill 私有的辅助程序 | `plugins/<domain>/skills/<skill>/scripts/` |
| MCP Tool | WHAT：多个 Skill/Plugin 共用的结构化 API | `mcp/<capability>/` |
| Subagent | WHO：拥有独立 context 的专门 worker | `plugins/<domain>/agents/<name>.md` |
| Hook | WHEN：lifecycle event 触发的自动化 | `plugins/<domain>/hooks/hooks.json` |
| Plugin | PACKAGE：可安装的领域能力包 | `plugins/<domain>/` |

判断标准：

- 只被一个 Skill 使用的小工具 → 该 Skill 的 `scripts/`。不要因为脚本能运行就包装成 MCP Tool。
- 多个 Skill / Plugin 都需要的通用能力 → `mcp/` 下的 MCP Tool。

## 共享 MCP 的方式：wrapper plugin + dependencies

Claude Code 的 plugin 通过 `.mcp.json`（或 `plugin.json` 的 `mcpServers`）注册 MCP server，
且 `plugin.json` 支持 `dependencies` 声明对其它 plugin 的依赖。因此：

```
mcp/konnect/plugin/              plugin "konnect"
├── .claude-plugin/plugin.json
└── .mcp.json                    {"mcpServers": {"konnect": {"command": "konnect"}}}

plugins/pcb-design/.claude-plugin/plugin.json   "dependencies": ["konnect"]
```

效果：

- MCP 的注册配置只有一份，在 `mcp/konnect/` 下；领域 plugin 里没有任何 MCP 文件。
- 安装 `pcb-design` 时，`konnect` 被自动安装；多个领域 plugin 都依赖它时也只启动**一个** MCP 进程。
- tool 名称固定为 `mcp__plugin_konnect_konnect__<tool>`，不随使用它的领域 plugin 变化。
  Subagent 的 `tools:` 可以写 `mcp__plugin_konnect_konnect`（该 server 的全部 tool）。

否决的方案：

- 在每个领域 plugin 里各写一份 `.mcp.json`：重复注册，tool 名称会带上各自的 plugin 前缀，Skill 无法用同一个名字引用。
- 在用户级 `~/.claude.json` 手工注册 MCP：不随 plugin 安装，无法通过 marketplace 复现。
- 自建依赖管理：官方 `dependencies` 已足够。

`plugin/` 放在 `mcp/<capability>/` 内部而不是 `plugins/` 下，是因为 `plugins/` 按领域划分，而 MCP 是公共能力；
同时把 plugin 根目录限定为 `plugin/` 子目录，避免安装时把源码、`.venv` 等拷进 plugin 缓存。

## 两种 MCP

| 类型 | 目录内容 | 可执行文件 |
|------|----------|------------|
| 本仓库实现的 MCP | `pyproject.toml`（`[project.scripts]`）、`src/`、`tests/`、`plugin/` | `plugin-install.sh --setup` 用 `uv tool install` 安装 |
| 外部 MCP（如 `konnect`） | `README.md`（安装说明）、`plugin/` | 由用户另行安装到 PATH；`--setup` 只检查，缺失时警告 |

两种 MCP 的 `.mcp.json` 都只写 PATH 上的命令名，不写指向本仓库或某台机器的绝对路径。

### konnect

[Konnect](https://github.com/mixelpixx/Konnect) 是一个 KiCad 插件，自带 `konnect` 可执行文件，通过 MCP 提供原理图和 PCB
工具（按 toolset 按需加载）。Konnect 不能完成的事情（画原理图分区线、改层叠、移动 PCB 位号等）由 `pcb-design`
各 Skill 的 `scripts/` 直接处理 KiCad 文件，并用 `kicad-cli` 验证。

## 扩展方式

```
plugins/                         mcp/
├── pcb-design/                  ├── konnect/       {README.md, plugin/}
├── <新领域>/                    ├── <新能力>/      {pyproject.toml, src/, tests/, plugin/}
└── ...                          └── ...
```

新增任何一项都只需加目录并在 `.claude-plugin/marketplace.json` 中登记，不改变整体结构。
`tests/test_repo_structure.py` 会检查这些约定（登记完整、领域 plugin 不含 MCP、每个 MCP 只注册一次、依赖可解析）。
