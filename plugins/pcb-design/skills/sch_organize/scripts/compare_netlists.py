#!/usr/bin/env python3
"""Check that two KiCad netlists (kicad-cli / Konnect generate_netlist, kicadsexpr format) connect
the same pins, i.e. that rearranging a schematic did not change its circuit.

    compare_netlists.py BEFORE.net AFTER.net

Nets are compared as sets of (reference, pin). Auto-generated names ("Net-(...)",
"unconnected-(...)") may change freely; a renamed named net (label, power rail) is reported.
Power and flag symbols (references starting with '#') are ignored.

Exit status: 0 identical connectivity, 1 differences, 2 a file could not be read.
"""

import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([()])|([^\s()"]+)')


def parse(text: str):
    stack, cur = [], []
    for quoted, paren, atom in TOKEN_RE.findall(text):
        if paren == "(":
            stack.append(cur)
            cur = []
        elif paren == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(quoted if atom == "" else atom)
    return cur[0]


def field(node: list, key: str):
    for child in node[1:]:
        if isinstance(child, list) and child and child[0] == key:
            return child[1] if len(child) > 1 else None
    return None


def nets(path: Path) -> dict[frozenset, str]:
    root = parse(path.read_text())
    section = next((c for c in root[1:] if isinstance(c, list) and c and c[0] == "nets"), None)
    if section is None:
        raise ValueError(f"{path}: no (nets ...) section; is it a kicadsexpr netlist?")
    result = {}
    for net in section[1:]:
        pins = frozenset(
            (field(n, "ref"), field(n, "pin"))
            for n in net[1:]
            if isinstance(n, list) and n and n[0] == "node" and not str(field(n, "ref")).startswith("#")
        )
        if pins:
            result[pins] = field(net, "name") or ""
    return result


def auto_name(name: str) -> bool:
    return name.startswith(("Net-(", "unconnected-(", "/Net-(")) or "/Net-(" in name


def fmt(pins: frozenset) -> str:
    return " ".join(f"{r}.{p}" for r, p in sorted(pins))


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        before, after = nets(Path(sys.argv[1])), nets(Path(sys.argv[2]))
    except (OSError, ValueError, IndexError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ok = True
    for pins in before.keys() - after.keys():
        ok = False
        print(f"LOST    {before[pins]}: {fmt(pins)}")
    for pins in after.keys() - before.keys():
        ok = False
        print(f"NEW     {after[pins]}: {fmt(pins)}")
    for pins in before.keys() & after.keys():
        old, new = before[pins], after[pins]
        if old != new and not (auto_name(old) and auto_name(new)):
            ok = False
            print(f"RENAMED {old} -> {new}: {fmt(pins)}")

    print(f"{len(before)} nets before, {len(after)} after: " + ("connectivity identical" if ok else "DIFFERENT"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
