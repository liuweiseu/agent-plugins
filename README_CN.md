# agent-plugins

[English](README.md) | **中文**

统一管理 Claude Code Plugin，以及被这些 Plugin 共用的 MCP 服务。

```
agent-plugins (marketplace: agent-plugins)
│
├── 领域 plugin ────────── pcb-design
│        │ dependencies
│        ▼
└── konnect (MCP plugin) ──► 外部 `konnect` 可执行文件（KiCad）
```

- **领域 Plugin**（`pcb-design`）：只包含各自的 Skills、Agents、Hooks。
- **konnect**：KiCad 原理图/PCB 设计的公共 MCP。服务端是外部的 [Konnect](https://github.com/mixelpixx/Konnect)
  可执行文件，本仓库只负责注册（`mcp/konnect/plugin/`）。通过 Claude Code 官方的 plugin `dependencies` 机制被领域 Plugin 共用。
- 设计说明见 [docs/architecture.md](docs/architecture.md)，日常开发见 [docs/development.md](docs/development.md)。

## Plugin 列表

| Plugin | 用途 |
|---|---|
| `pcb-design` | KiCad 原理图整理、PCB 板子定义和子模块布局 |
| `konnect` | 公共 MCP，注册 Konnect 的 KiCad 工具；作为依赖自动安装 |

`pcb-design` 声明了 `"dependencies": ["konnect"]`。它包含的 Skill：

| Skill | 用途 |
|---|---|
| `sch_organize` | 把每页原理图拆成相互独立的子模块，用分区线把整页分成带名字的区域 |
| `pcb_board_info` | 按 JSON 描述设置板子：外形（矩形/圆形）、安装孔、层叠、板边间距 |
| `pcb_submodule_placement` | 把原理图中的一个子模块布局到 PCB 上（去耦电容、滤波电容、丝印） |

## 目录结构

```
agent-plugins/
├── .claude-plugin/marketplace.json   # marketplace "agent-plugins"：列出所有 plugin
├── plugins/                          # 领域 Plugin（按领域划分）
│   └── pcb-design/   {.claude-plugin/plugin.json, skills/, agents/, hooks/}
├── mcp/                              # 公共 MCP（按能力划分）
│   └── konnect/                      # 外部 MCP：只有注册用的 plugin（.mcp.json command: konnect）
├── tools/{plugin-install.sh, validate.sh}
├── tests/                            # 仓库架构规则测试
└── docs/
```

## 前提

- [uv](https://docs.astral.sh/uv/)、`claude`（Claude Code CLI）
- 使用 `pcb-design` 时：KiCad（含 `kicad-cli`）和 [Konnect](https://github.com/mixelpixx/Konnect) 插件，且其 `konnect`
  可执行文件在 PATH 上（例如 `ln -s <konnect>/plugins/bin/konnect ~/.local/bin/konnect`）。

## 快速开始：按项目选择 plugin

Plugin 不做全局安装，而是**按项目目录启用**：在哪个目录打开 Claude Code，就只加载为该目录选定的 plugin。

一次性准备（只有这一次需要写完整路径）：

```bash
/home/agent/Projects/agent-plugins/tools/plugin-install.sh --setup
```

它会检查 MCP 可执行文件、注册 marketplace，并把 `plugin-install.sh` 链接到 `~/.local/bin`，之后在任何目录都能直接运行。
（第一次带 plugin 名运行时也会自动完成这一步。）

然后，每个项目：

```bash
cd ~/work/my-board
plugin-install.sh pcb-design      # 这个目录只用 PCB 设计
claude
```

更多用法：

```bash
plugin-install.sh -C ~/work/other pcb-design         # 用 -C 指定项目目录，可同时选多个
plugin-install.sh --remove pcb-design                # 在当前目录停用
plugin-install.sh                                    # 列出可用 plugin 和用法
plugin-install.sh --setup                            # 修改 MCP 代码后重新执行
tools/validate.sh                                    # 校验仓库
```

效果：

| 打开 Claude Code 的目录 | 加载的 plugin | konnect MCP |
|---|---|---|
| `~/work/my-board` | pcb-design + konnect | ✔ |
| 其他任何目录 | 无 | 不启动 |

### 选择记录在哪里（`-s/--scope`）

| scope | 写入 | 生效范围 |
|---|---|---|
| `local`（默认） | `<项目>/.claude/settings.local.json` | 仅自己、仅该项目 |
| `project` | `<项目>/.claude/settings.json` | 提交到 git 后，所有使用该项目的人 |
| `user` | `~/.claude/settings.json` | 自己的所有项目（全局，一般不需要） |

例如 `local` 会写入：

```json
{
  "enabledPlugins": { "pcb-design@agent-plugins": true, "konnect@agent-plugins": true },
  "permissions": { "allow": ["Read(//home/agent/Projects/agent-plugins/**)"] }
}
```

`konnect` 由 `dependencies` 自动带入同一 scope；`--remove` 时如果没有其他 plugin 需要它，会一起移除。

`Read` 规则让 Claude 读取 plugin 文件（skill 用到的共享 `scripts/` 和 `references/`）时不再弹权限确认：这些文件在本仓库里，
位于项目目录之外。启用 plugin 时加入，`--remove` 后如果该设置文件里已没有本仓库的 plugin 就移除；文件里的其他设置保持不变。

### plugin-install.sh 做了什么（也可以手工执行）

准备（一次，或 `--setup`）：

1. **检查 MCP 可执行文件**：本仓库自己实现的 MCP（`mcp/<name>/pyproject.toml`）用 `uv tool install --reinstall` 安装；
   `konnect` 这类外部 MCP 只做检查，不在 PATH 上时给出警告。
2. **注册 marketplace**：`claude plugin marketplace add /home/agent/Projects/agent-plugins`。
   marketplace 只是一个目录，注册它不会在任何项目中启用 plugin。
3. **链接脚本**：`~/.local/bin/plugin-install.sh -> /home/agent/Projects/agent-plugins/tools/plugin-install.sh`。

每次带 plugin 名运行（约一秒）：

4. **在选定的项目中启用 plugin**：

   ```bash
   cd <项目> && claude plugin install --scope local pcb-design@agent-plugins
   cd <项目> && claude plugin uninstall --scope local --prune pcb-design@agent-plugins   # 停用
   ```

### 只在一个会话中加载 plugin

scope 按**目录**生效。想不安装就试用某个 plugin，可以在启动时加载（只影响这个会话，不写任何配置）：

```bash
R=/home/agent/Projects/agent-plugins
claude --plugin-dir $R/plugins/pcb-design --plugin-dir $R/mcp/konnect/plugin
```

`--plugin-dir` 绕过 marketplace，所以 MCP plugin 目录也要一起传入：缺少依赖的 plugin 会被静默跳过（没有 skill，也没有报错）。

## 验证

### 验证 Plugin

```bash
claude plugin validate --strict .                    # marketplace
claude plugin validate --strict plugins/pcb-design
claude plugin validate --strict mcp/konnect/plugin
claude plugin list                                   # 在项目目录中运行：已选的 plugin 为 enabled
python3 -m unittest discover -s tests -t . -v        # 仓库架构规则
```

### 验证 MCP

```bash
cd <项目> && claude mcp list                          # 在启用了 plugin 的项目目录中运行
# plugin:konnect:konnect: konnect  - ✔ Connected
```

在会话中输入 `/mcp` 可以看到 `plugin:konnect:konnect`；它的 tool 名称为 `mcp__plugin_konnect_konnect__<tool>`。

## 扩展

- 新领域：`plugins/<name>/`，并在 `marketplace.json` 中登记。
- 新公共能力：`mcp/<name>/`（带 `plugin/` 包装），在 `marketplace.json` 中登记；需要它的 plugin 在 `dependencies` 中声明。
- 详见 [docs/development.md](docs/development.md)。
