# konnect

Wrapper plugin that registers the external [Konnect](https://github.com/mixelpixx/Konnect) MCP server
(KiCad schematic/PCB design tools) with Claude Code. The server itself is not part of this repository:
it ships as a prebuilt binary inside the Konnect KiCad plugin.

Make its `konnect` executable available on PATH, e.g.:

```bash
ln -sfn /path/to/konnect/plugins/bin/konnect ~/.local/bin/konnect
```

Domain plugins that need it (e.g. `pcb-design`) declare `"dependencies": ["konnect"]`.
