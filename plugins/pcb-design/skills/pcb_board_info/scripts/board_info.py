#!/usr/bin/env python3
"""Apply a board description (outline, mounting holes, stackup, edge clearance) to a KiCad board.

    board_info.py check SPEC.json
    board_info.py apply SPEC.json BOARD.kicad_pcb [--replace] [--dry-run] [--footprint-dir DIR]

SPEC.json (see ../references/board-spec.md and ../references/examples/) uses millimetres, with
the board's bottom-left corner as (0, 0) and y pointing up; it is converted to KiCad coordinates
(y down) here. `origin` is where the bottom-left corner goes in KiCad; by default the board's
top-left corner lands at (100, 100).

check: validates the spec and prints it in KiCad coordinates (outline, hole positions,
stackup layers) with warnings. Nothing is written.

apply: edits the board file (it must not be open in KiCad, which would overwrite it on save):
  - outline: written on Edge.Cuts. A board that already has Edge.Cuts graphics is refused
    unless --replace, which removes them first;
  - mounting holes: KiCad's MountingHole library footprints (plated ones: the _Pad variant),
    references H1, H2, ... after the existing ones. --replace also removes the board-only
    MountingHole footprints already there; ones linked to a schematic symbol are kept and listed;
  - stackup: copper layer count (inner layers In1.Cu ...), board thickness and the physical
    stackup (dielectrics share what copper and solder mask leave of the thickness), optional
    surface finish. Removing inner layers that still carry anything is refused;
  - edge_clearance: min_copper_edge_clearance in the project's .kicad_pro next to the board.
--dry-run reports what would change without writing.

Exit status: 0 ok, 1 invalid spec or refused change, 2 error.
"""

import argparse
import json
import math
import os
import re
import sys
import uuid
from pathlib import Path

OUTER_COPPER = 0.035
MASK = 0.01
MIN_DIELECTRIC = 0.05
EDGE_WIDTH = 0.05
KNOWN_FINISHES = ["None", "HAL SnPb", "HAL lead-free", "ENIG", "ENEPIG", "Hard gold", "Immersion tin",
                  "Immersion nickel", "Immersion silver", "Immersion gold", "OSP", "HT_OSP", "User defined"]
FOOTPRINT_DIRS = [
    "/usr/share/kicad/footprints", "/usr/local/share/kicad/footprints",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
    "C:/Program Files/KiCad/10.0/share/kicad/footprints",
]
GRAPHIC_RE = re.compile(r"^\((gr_line|gr_arc|gr_circle|gr_rect|gr_poly|gr_curve)\b")


class SpecError(Exception):
    pass


# ---------------------------------------------------------------- spec

def num(obj: dict, key: str, where: str, minimum: float | None = 0.0, default=None) -> float:
    value = obj.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SpecError(f"{where}.{key}: a number is required")
    if minimum is not None and value <= minimum:
        raise SpecError(f"{where}.{key}: must be greater than {minimum:g}")
    return float(value)


def point(value, where: str) -> tuple[float, float]:
    if (not isinstance(value, list) or len(value) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
        raise SpecError(f"{where}: [x, y] is required")
    return float(value[0]), float(value[1])


def load_spec(path: Path) -> tuple[dict, list[str]]:
    """Validate SPEC.json; return it in KiCad coordinates plus warnings."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecError(f"{path}: {exc}")
    if not isinstance(raw, dict):
        raise SpecError("the spec must be a JSON object")
    if raw.get("version", 1) != 1:
        raise SpecError("version: only 1 is supported")
    if raw.get("units", "mm") != "mm":
        raise SpecError("units: only \"mm\" is supported")
    unknown = set(raw) - {"version", "name", "units", "origin", "outline", "mounting_holes", "stackup",
                          "edge_clearance", "comment"}
    if unknown:
        raise SpecError(f"unknown keys: {', '.join(sorted(unknown))}")
    warnings: list[str] = []

    outline = raw.get("outline")
    if not isinstance(outline, dict):
        raise SpecError("outline: an object is required")
    shape = outline.get("shape")
    if shape == "rectangle":
        w, h = num(outline, "width", "outline"), num(outline, "height", "outline")
    elif shape == "circle":
        w = h = num(outline, "diameter", "outline")
    else:
        raise SpecError("outline.shape: \"rectangle\" or \"circle\"")

    ox, oy = point(raw["origin"], "origin") if "origin" in raw else (100.0, 100.0 + h)

    def kicad(x: float, y: float) -> list[float]:
        return [round(ox + x, 4), round(oy - y, 4)]

    if shape == "rectangle":
        board = {"shape": "rectangle", "start": kicad(0, h), "end": kicad(w, 0), "width": w, "height": h}
    else:
        board = {"shape": "circle", "center": kicad(w / 2, w / 2), "diameter": w}

    edge = raw.get("edge_clearance")
    if edge is not None:
        edge = num(raw, "edge_clearance", "spec", minimum=None)
        if edge < 0:
            raise SpecError("edge_clearance: must not be negative")

    holes = []
    for i, item in enumerate(raw.get("mounting_holes", [])):
        where = f"mounting_holes[{i}]"
        if not isinstance(item, dict):
            raise SpecError(f"{where}: an object is required")
        drill = num(item, "drill", where)
        plated = item.get("plated", False)
        if not isinstance(plated, bool):
            raise SpecError(f"{where}.plated: true or false")
        pattern = item.get("pattern")
        if pattern is None:
            positions = [point(item.get("at"), f"{where}.at")]
        elif pattern == "corners":
            if shape != "rectangle":
                raise SpecError(f"{where}: pattern \"corners\" needs a rectangular outline")
            d = num(item, "inset", where)
            positions = [(d, d), (w - d, d), (w - d, h - d), (d, h - d)]
        elif pattern == "polar":
            if shape != "circle":
                raise SpecError(f"{where}: pattern \"polar\" needs a circular outline")
            count = item.get("count")
            if not isinstance(count, int) or isinstance(count, bool) or count < 1:
                raise SpecError(f"{where}.count: a positive integer is required")
            d = num(item, "inset", where)
            start = num(item, "start_angle", where, minimum=None, default=45)
            r, c = w / 2 - d, w / 2
            positions = [(c + r * math.cos(math.radians(start + k * 360 / count)),
                          c + r * math.sin(math.radians(start + k * 360 / count))) for k in range(count)]
        else:
            raise SpecError(f"{where}.pattern: \"corners\" or \"polar\"")
        for x, y in positions:
            holes.append({"local": [round(x, 4), round(y, 4)], "at": kicad(x, y), "drill": drill, "plated": plated})

    for i, hole in enumerate(holes):
        x, y = hole["local"]
        r = hole["drill"] / 2
        if shape == "rectangle":
            gap = min(x, y, w - x, h - y) - r
        else:
            gap = w / 2 - math.hypot(x - w / 2, y - w / 2) - r
        if gap < 0:
            raise SpecError(f"mounting hole at ({x:g}, {y:g}) (drill {hole['drill']:g}) crosses the board edge")
        if gap < max(edge or 0, 1.0):
            warnings.append(f"mounting hole at ({x:g}, {y:g}): only {gap:.2f} mm from the board edge")
        for other in holes[i + 1:]:
            ox2, oy2 = other["local"]
            if math.hypot(x - ox2, y - oy2) < r + other["drill"] / 2:
                raise SpecError(f"mounting holes at ({x:g}, {y:g}) and ({ox2:g}, {oy2:g}) overlap")

    stackup = raw.get("stackup")
    if stackup is not None:
        if not isinstance(stackup, dict):
            raise SpecError("stackup: an object is required")
        n = stackup.get("copper_layers")
        if not isinstance(n, int) or isinstance(n, bool) or n < 2 or n > 32 or n % 2:
            raise SpecError("stackup.copper_layers: an even number from 2 to 32")
        t = num(stackup, "thickness", "stackup")
        dielectric = (t - 2 * MASK - n * OUTER_COPPER) / (n - 1)
        if dielectric < MIN_DIELECTRIC:
            raise SpecError(f"stackup: {t:g} mm is too thin for {n} copper layers")
        finish = stackup.get("finish")
        if finish is not None and not isinstance(finish, str):
            raise SpecError("stackup.finish: a string is required")
        if finish and finish not in KNOWN_FINISHES:
            warnings.append(f"stackup.finish {finish!r} is not one of KiCad's: {', '.join(KNOWN_FINISHES)}")
        stackup = {"copper_layers": n, "thickness": t, "dielectric": round(dielectric, 6), "finish": finish}

    spec = {"name": raw.get("name", ""), "outline": board, "mounting_holes": holes,
            "stackup": stackup, "edge_clearance": edge}
    return spec, warnings


# ---------------------------------------------------------------- s-expression spans

def children(text: str, start: int = -1, end: int | None = None) -> list[tuple[int, int]]:
    """Spans of the direct children of the list starting at `start` (-1: the root list)."""
    if start < 0:
        start = text.index("(")
    end = len(text) if end is None else end
    spans, depth, child, i, in_str = [], 0, 0, start, False
    while i < end:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
            if depth == 2:
                child = i
        elif c == ")":
            if depth == 2:
                spans.append((child, i + 1))
            depth -= 1
            if depth == 0:
                break
        i += 1
    return spans


def head(item: str) -> str:
    m = re.match(r"\(([^\s()]+)", item)
    return m.group(1) if m else ""


def find_child(text: str, name: str, start: int = -1) -> tuple[int, int] | None:
    return next(((s, e) for s, e in children(text, start) if head(text[s:e]) == name), None)


def remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    for s, e in sorted(spans, reverse=True):
        while s > 0 and text[s - 1] in " \t":
            s -= 1
        if text[e:e + 1] == "\n":
            e += 1
        text = text[:s] + text[e:]
    return text


def append_root(text: str, items: str) -> str:
    end = text.rstrip().rfind(")")
    return text[:end].rstrip("\n\t ") + "\n" + items + ")\n"


def indent(block: str, tabs: int) -> str:
    return "\n".join(("\t" * tabs + line) if line.strip() else line for line in block.splitlines()) + "\n"


# ---------------------------------------------------------------- outline

def outline_items(spec: dict) -> str:
    o = spec["outline"]
    stroke = f"(stroke\n\t(width {EDGE_WIDTH:g})\n\t(type default)\n)"
    if o["shape"] == "rectangle":
        body = (f"(gr_rect\n\t(start {o['start'][0]:g} {o['start'][1]:g})\n\t(end {o['end'][0]:g} {o['end'][1]:g})\n"
                f"{indent(stroke, 1)}\t(fill no)\n\t(layer \"Edge.Cuts\")\n\t(uuid \"{uuid.uuid4()}\")\n)")
    else:
        cx, cy = o["center"]
        body = (f"(gr_circle\n\t(center {cx:g} {cy:g})\n\t(end {cx + o['diameter'] / 2:g} {cy:g})\n"
                f"{indent(stroke, 1)}\t(fill no)\n\t(layer \"Edge.Cuts\")\n\t(uuid \"{uuid.uuid4()}\")\n)")
    return indent(body, 1)


def edge_cut_spans(text: str) -> list[tuple[int, int]]:
    return [(s, e) for s, e in children(text) if GRAPHIC_RE.match(text[s:e]) and '(layer "Edge.Cuts")' in text[s:e]]


# ---------------------------------------------------------------- mounting holes

def footprint_dir(override: str | None) -> Path:
    candidates = [override] if override else [
        os.environ.get(v) for v in ("KICAD10_FOOTPRINT_DIR", "KICAD9_FOOTPRINT_DIR", "KICAD_FOOTPRINT_DIR")
    ] + FOOTPRINT_DIRS
    for c in candidates:
        if c and (Path(c) / "MountingHole.pretty").is_dir():
            return Path(c) / "MountingHole.pretty"
    raise SpecError("KiCad's MountingHole.pretty library was not found; pass --footprint-dir")


def hole_footprint(lib: Path, drill: float, plated: bool) -> Path:
    pattern = re.compile(rf"^MountingHole_{re.escape(f'{drill:g}')}mm(_M[\d.]+)?{'_Pad' if plated else ''}\.kicad_mod$")
    matches = sorted(p for p in lib.iterdir() if pattern.match(p.name))
    if not matches:
        sizes = sorted({float(m.group(1)) for p in lib.iterdir()
                        if (m := re.match(r"^MountingHole_([\d.]+)mm(_M[\d.]+)?(_Pad)?\.kicad_mod$", p.name))})
        raise SpecError(f"no {'plated ' if plated else ''}MountingHole footprint for a {drill:g} mm drill; "
                        f"available: {', '.join(f'{s:g}' for s in sizes)}")
    return matches[0]


def hole_item(mod: Path, ref: str, x: float, y: float) -> str:
    text = mod.read_text()
    drop = [(s, e) for s, e in children(text) if head(text[s:e]) in ("version", "generator", "generator_version")]
    text = remove_spans(text, drop)
    text = re.sub(r'^\(footprint "([^"]+)"', r'(footprint "MountingHole:\1"', text, count=1)
    text = re.sub(r'(\(property "Reference" )"[^"]*"', rf'\1"{ref}"', text, count=1)
    layer = find_child(text, "layer")
    at = f'\n\t(uuid "{uuid.uuid4()}")\n\t(at {x:g} {y:g})'
    text = text[:layer[1]] + at + text[layer[1]:]
    return indent(text.strip(), 1)


def mounting_hole_spans(text: str) -> tuple[list, list]:
    """Board-only MountingHole footprints, and ones linked to a schematic symbol (reference list)."""
    board_only, linked = [], []
    for s, e in children(text):
        item = text[s:e]
        if item.startswith('(footprint "MountingHole:'):
            if find_child(item, "path"):
                ref = re.search(r'\(property "Reference" "([^"]*)"', item)
                linked.append(ref.group(1) if ref else "?")
            else:
                board_only.append((s, e))
    return board_only, linked


def next_refs(text: str, count: int) -> list[str]:
    used = {int(n) for n in re.findall(r'\(property "Reference" "H(\d+)"', text)}
    refs, n = [], 1
    while len(refs) < count:
        if n not in used:
            refs.append(f"H{n}")
        n += 1
    return refs


# ---------------------------------------------------------------- stackup

def copper_names(n: int) -> list[str]:
    return ["F.Cu"] + [f"In{i}.Cu" for i in range(1, n - 1)] + ["B.Cu"]


def rewrite_layers(text: str, n: int) -> tuple[str, list[str]]:
    span = find_child(text, "layers")
    if not span:
        raise SpecError("the board has no (layers ...) table")
    s, e = span
    entries = [text[a:b] for a, b in children(text, s)]
    current = [m.group(1) for x in entries if (m := re.match(r'\(\d+ "(In\d+\.Cu)"', x))]
    b_cu = next((int(m.group(1)) for x in entries if (m := re.match(r'\((\d+) "B\.Cu"', x))), 2)
    legacy = b_cu == 31   # before KiCad 9 inner layers were numbered 1..30
    wanted = copper_names(n)[1:-1]
    removed = [l for l in current if l not in wanted]
    kept = [x for x in entries if not re.match(r'\(\d+ "In\d+\.Cu"', x)]
    inner = [f'({i if legacy else 2 * i + 2} "In{i}.Cu" signal)' for i in range(1, n - 1)]
    f_cu = next(i for i, x in enumerate(kept) if re.match(r'\(\d+ "F\.Cu"', x))
    kept[f_cu + 1:f_cu + 1] = inner
    block = "(layers\n" + "".join(f"\t\t{x}\n" for x in kept) + "\t)"
    return text[:s] + block + text[e:], removed


def layer_in_use(text: str, layer: str) -> int:
    """Occurrences of a layer name outside the layers table and the stackup."""
    skip = [find_child(text, "layers")]
    setup = find_child(text, "setup")
    if setup:
        skip.append(find_child(text, "stackup", setup[0]))
    count = 0
    for m in re.finditer(re.escape(f'"{layer}"'), text):
        if not any(sp and sp[0] <= m.start() < sp[1] for sp in skip):
            count += 1
    return count


def stackup_block(old: str | None, st: dict) -> str:
    def prop(layer: str, key: str, default: str | None) -> str | None:
        if old:
            m = re.search(rf'\(layer "{re.escape(layer)}"(.*?)\n\t*\)', old, re.S)
            if m and (v := re.search(rf"\({key} ([^)]*)\)", m.group(1))):
                return v.group(1)
        return default

    extras = []
    if old:
        extras = [old[a:b] for a, b in children(old, 0)
                  if head(old[a:b]) != "layer" and not (st["finish"] and head(old[a:b]) == "copper_finish")]
    if st["finish"] or not any(head(x) == "copper_finish" for x in extras):
        extras.insert(0, f'(copper_finish "{st["finish"] or "None"}")')
    if not any(head(x) == "dielectric_constraints" for x in extras):
        extras.append("(dielectric_constraints no)")

    material = prop("dielectric 1", "material", '"FR4"')
    eps = prop("dielectric 1", "epsilon_r", "4.5")
    loss = prop("dielectric 1", "loss_tangent", "0.02")
    layers = []

    def add(name: str, *props: str) -> None:
        layers.append(f'(layer "{name}"\n' + "".join(f"\t{p}\n" for p in props if p) + ")")

    def colour(name: str, default: str) -> str:
        return f"(color {prop(name, 'color', default)})"

    add("F.SilkS", '(type "Top Silk Screen")', colour("F.SilkS", '"White"'))
    add("F.Paste", '(type "Top Solder Paste")')
    add("F.Mask", '(type "Top Solder Mask")', colour("F.Mask", '"Green"'), f"(thickness {MASK:g})")
    names = copper_names(st["copper_layers"])
    for i, cu in enumerate(names):
        add(cu, '(type "copper")', f"(thickness {OUTER_COPPER:g})")
        if i < len(names) - 1:
            kind = "core" if i % 2 == 0 else "prepreg"
            add(f"dielectric {i + 1}", f'(type "{kind}")', f"(thickness {st['dielectric']:g})",
                f"(material {material})", f"(epsilon_r {eps})", f"(loss_tangent {loss})")
    add("B.Mask", '(type "Bottom Solder Mask")', colour("B.Mask", '"Green"'), f"(thickness {MASK:g})")
    add("B.Paste", '(type "Bottom Solder Paste")')
    add("B.SilkS", '(type "Bottom Silk Screen")', colour("B.SilkS", '"White"'))
    body = "\n".join(layers + extras)
    return "(stackup\n" + indent(body, 1) + ")"


def rewrite_stackup(text: str, st: dict) -> tuple[str, list[str]]:
    text, removed = rewrite_layers(text, st["copper_layers"])
    busy = [f"{l} ({n} item(s))" for l in removed if (n := layer_in_use(text, l))]
    if busy:
        raise SpecError("cannot remove inner layers that are still in use: " + ", ".join(busy))

    setup = find_child(text, "setup")
    if not setup:
        layers = find_child(text, "layers")
        text = text[:layers[1]] + "\n\t(setup\n\t)" + text[layers[1]:]
        setup = find_child(text, "setup")
    old = find_child(text, "stackup", setup[0])
    new = indent(stackup_block(text[old[0]:old[1]] if old else None, st), 2).strip()
    if old:
        text = text[:old[0]] + new + text[old[1]:]
    else:
        pos = text.index("(setup", setup[0]) + len("(setup")
        text = text[:pos] + "\n\t\t" + new + text[pos:]

    general = find_child(text, "general")
    if general:
        block = text[general[0]:general[1]]
        if "(thickness" in block:
            block = re.sub(r"\(thickness [^)]*\)", f"(thickness {st['thickness']:g})", block, count=1)
        else:
            block = block[:-1].rstrip() + f"\n\t\t(thickness {st['thickness']:g})\n\t)"
        text = text[:general[0]] + block + text[general[1]:]
    return text, removed


# ---------------------------------------------------------------- main

def apply(spec: dict, board: Path, args) -> int:
    text = board.read_text()
    if not text.lstrip().startswith("(kicad_pcb"):
        print(f"error: {board} is not a KiCad board", file=sys.stderr)
        return 2
    report = []

    old_edges = edge_cut_spans(text)
    if old_edges and not args.replace:
        print(f"refused: {board} already has {len(old_edges)} Edge.Cuts item(s); use --replace to replace the outline")
        return 1
    text = remove_spans(text, old_edges)
    o = spec["outline"]
    report.append(f"outline: {o['shape']} "
                  + (f"{o['width']:g} x {o['height']:g} mm" if o["shape"] == "rectangle" else f"diameter {o['diameter']:g} mm")
                  + (f" (replaced {len(old_edges)} Edge.Cuts item(s))" if old_edges else ""))
    text = append_root(text, outline_items(spec))

    if spec["mounting_holes"] or args.replace:
        board_only, linked = mounting_hole_spans(text)
        if args.replace and board_only:
            text = remove_spans(text, board_only)
            report.append(f"removed {len(board_only)} board-only mounting hole(s)")
        if linked:
            report.append(f"kept mounting holes linked to the schematic: {', '.join(linked)}")
    if spec["mounting_holes"]:
        lib = footprint_dir(args.footprint_dir)
        refs = next_refs(text, len(spec["mounting_holes"]))
        items = ""
        for ref, hole in zip(refs, spec["mounting_holes"]):
            mod = hole_footprint(lib, hole["drill"], hole["plated"])
            items += hole_item(mod, ref, *hole["at"])
            report.append(f"{ref}: {mod.stem} at ({hole['local'][0]:g}, {hole['local'][1]:g}) "
                          f"= KiCad ({hole['at'][0]:g}, {hole['at'][1]:g})")
        text = append_root(text, items)

    if spec["stackup"]:
        st = spec["stackup"]
        text, removed = rewrite_stackup(text, st)
        report.append(f"stackup: {st['copper_layers']} copper layers, {st['thickness']:g} mm, "
                      f"dielectrics {st['dielectric']:g} mm" + (f", finish {st['finish']}" if st["finish"] else "")
                      + (f" (removed {', '.join(removed)})" if removed else ""))

    pro = board.with_suffix(".kicad_pro")
    pro_data = None
    if spec["edge_clearance"] is not None:
        if pro.exists():
            pro_data = json.loads(pro.read_text())
            rules = pro_data.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
            rules["min_copper_edge_clearance"] = spec["edge_clearance"]
            report.append(f"edge clearance: {spec['edge_clearance']:g} mm in {pro.name}")
        else:
            report.append(f"WARNING edge clearance not set: {pro} does not exist")

    if not args.dry_run:
        board.write_text(text)
        if pro_data is not None:
            pro.write_text(json.dumps(pro_data, indent=2, ensure_ascii=False) + "\n")
    print(("dry run, nothing written: " if args.dry_run else f"updated {board}: ") + "\n  " + "\n  ".join(report))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["check", "apply"])
    ap.add_argument("spec", type=Path)
    ap.add_argument("board", type=Path, nargs="?")
    ap.add_argument("--replace", action="store_true", help="replace the existing outline and board-only mounting holes")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--footprint-dir", help="KiCad footprint library directory (contains MountingHole.pretty)")
    args = ap.parse_args()

    try:
        spec, warnings = load_spec(args.spec)
        for w in warnings:
            print(f"WARNING {w}")
        if args.action == "check":
            print(json.dumps(spec, ensure_ascii=False, indent=2))
            return 0
        if args.board is None:
            ap.error("apply needs BOARD.kicad_pcb")
        return apply(spec, args.board, args)
    except SpecError as exc:
        print(f"invalid: {exc}")
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
