"""Architecture rules for the repository (stdlib only; run with tools/validate.sh).

- every plugin is listed in the marketplace, and every marketplace entry exists
- domain plugins never bundle MCP implementations; shared MCP servers live once under mcp/
- an MCP server is registered with Claude Code by exactly one wrapper plugin
- domain plugins reach shared MCP servers through plugin "dependencies"
"""

from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKETPLACE = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
ENTRIES = {p["name"]: REPO / p["source"] for p in MARKETPLACE["plugins"]}
DOMAIN_PLUGINS = sorted(p.parent.parent for p in (REPO / "plugins").glob("*/.claude-plugin/plugin.json"))
MCP_PACKAGES = sorted(p.parent.parent.parent for p in (REPO / "mcp").glob("*/plugin/.claude-plugin/plugin.json"))


def manifest(plugin_dir: Path) -> dict:
    return json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())


def mcp_servers(plugin_dir: Path) -> dict:
    path = plugin_dir / ".mcp.json"
    servers = json.loads(path.read_text())["mcpServers"] if path.exists() else {}
    return {**servers, **manifest(plugin_dir).get("mcpServers", {})}


class MarketplaceTest(unittest.TestCase):
    def test_entries_point_to_plugins_with_matching_names(self):
        for name, path in ENTRIES.items():
            with self.subTest(plugin=name):
                self.assertTrue((path / ".claude-plugin" / "plugin.json").is_file(), f"{path} has no plugin.json")
                self.assertEqual(manifest(path)["name"], name)

    def test_every_domain_plugin_is_listed(self):
        listed = {p.resolve() for p in ENTRIES.values()}
        for plugin in DOMAIN_PLUGINS:
            with self.subTest(plugin=plugin.name):
                self.assertIn(plugin.resolve(), listed)

    def test_every_mcp_wrapper_plugin_is_listed(self):
        self.assertTrue(MCP_PACKAGES, "no mcp/*/plugin wrappers found")
        listed = {p.resolve() for p in ENTRIES.values()}
        for pkg in MCP_PACKAGES:
            with self.subTest(mcp=pkg.name):
                self.assertIn((pkg / "plugin").resolve(), listed)


class McpBoundaryTest(unittest.TestCase):
    def test_domain_plugins_do_not_bundle_mcp(self):
        for plugin in DOMAIN_PLUGINS:
            with self.subTest(plugin=plugin.name):
                self.assertFalse((plugin / "mcp").exists(), "MCP implementations belong under mcp/")
                self.assertEqual(mcp_servers(plugin), {}, "register shared MCP servers via a dependency instead")

    def test_wrapper_plugins_launch_installed_executables(self):
        for pkg in MCP_PACKAGES:
            pyproject = pkg / "pyproject.toml"
            # Without a pyproject the server is external (e.g. konnect) and must already be on PATH.
            scripts = tomllib.loads(pyproject.read_text())["project"]["scripts"] if pyproject.exists() else None
            for name, server in mcp_servers(pkg / "plugin").items():
                with self.subTest(mcp=pkg.name, server=name):
                    # Installed with `uv tool install` or externally, never a path into this repository.
                    if scripts is None:
                        self.assertNotIn("/", server["command"])
                    else:
                        self.assertIn(server["command"], scripts)

    def test_each_mcp_server_is_registered_once(self):
        seen: dict[str, str] = {}
        for name, path in ENTRIES.items():
            for server in mcp_servers(path):
                with self.subTest(server=server):
                    self.assertNotIn(server, seen, f"also registered by {seen.get(server)}")
                    seen[server] = name

    def test_dependencies_resolve_within_marketplace(self):
        for plugin in DOMAIN_PLUGINS:
            for dep in manifest(plugin).get("dependencies", []):
                dep_name = dep["name"] if isinstance(dep, dict) else dep.split("@")[0]
                with self.subTest(plugin=plugin.name, dependency=dep_name):
                    self.assertIn(dep_name, ENTRIES)


if __name__ == "__main__":
    unittest.main()
