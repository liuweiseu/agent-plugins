#!/usr/bin/env python3
"""Divide a KiCad schematic sheet into module regions with blue dashed lines (sch_organize).

    sch_regions.py plan   SHEET.kicad_sch MODULES.json [--pad MM] [--paper SIZE] [--grid COLSxROWS]
    sch_regions.py draw   SHEET.kicad_sch REGIONS.json
    sch_regions.py list   SHEET.kicad_sch
    sch_regions.py remove SHEET.kicad_sch
    sch_regions.py parts  SHEET.kicad_sch|PROJECT_DIR NAME
    common options: [--inset MM] [--title-block WxH]

plan: MODULES.json lists the sheet's modules in the order they should be laid out (left to right,
top to bottom), each with the size of its content in mm:

    [{"name": "3V3 LDO (U3)", "w": 60, "h": 40}, ...]

and prints REGIONS.json: rectangles tiling the drawing area of the page frame, one per module,
each big enough for its content plus --pad (default 5.08 mm) and a name band. `place_x`/`place_y`
is the top-left corner where the module's content goes. Rows that do not fill the page are
stretched to fill it. Exit 1 when the modules do not fit; the output then names the smallest
standard paper they fit on (try it with --paper, change the page only with the user's consent).
With --grid COLSxROWS (e.g. 2x3, for sheets of repeated units) the frame is divided into equal
cells instead, filled with the modules row by row; when there are more cells than modules, the
cell holding the title block stays empty first. Exit 1 when a module is larger than a cell.

draw: draws the borders between the regions of REGIONS.json (plan's output, possibly edited) as
blue dashed lines (KiCad "Draw Lines" polylines) and each region's name in its top-left corner.
Borders on the page frame are not drawn, lines are clipped at the title block. Lines and names
drawn earlier by this script are replaced, so it can be re-run after any change. Only items with
this script's style (dash, colour 0 0 255) are treated as its own; nothing else is touched.
Exit 1 when regions overlap or leave the frame (still drawn; fix and re-run).

parts: finds the region named NAME (its blue name text; searched in every sheet under
PROJECT_DIR when a directory is given), works out the region's rectangle from the region lines
around the name, and prints JSON with the sheet, the rectangle and the parts placed inside it
(reference, value, footprint, lib_id; power and flag symbols left out). A name matching no
region exactly is looked up ignoring case and as a substring; several matches exit 2 and are
listed. For a sheet used by several sheet instances, every instance's reference is listed.

The frame is the default KiCad drawing sheet: the paper inset by --inset (default 12 mm) on every
side, with the title block (--title-block, default 108x32 mm) in its bottom-right corner.

Exit status: 0 ok, 1 see above, 2 error.
"""

import argparse
import json
import math
import re
import sys
import uuid
from pathlib import Path

GRID = 2.54
NAME_BAND = 5.08
COLOR = "(color 0 0 255 1)"
OWN_GRAPHIC_RE = re.compile(r"\((?:polyline|rectangle)\b.*\(type dash\).*\(color 0 0 255 1\)", re.S)
OWN_TEXT_RE = re.compile(r"\(text\b.*\(color 0 0 255 1\)", re.S)
TEXT_NAME_RE = re.compile(r'\(text\s+("(?:[^"\\]|\\.)*")')
XY_RE = re.compile(r"\((?:xy|start|end) ([-\d.]+) ([-\d.]+)\)")
SYMBOL_AT_RE = re.compile(r"^\(symbol\s.*?\(at ([-\d.]+) ([-\d.]+)", re.S)
TEXT_AT_RE = re.compile(r"\(at ([-\d.]+) ([-\d.]+)")
LIB_ID_RE = re.compile(r'\(lib_id "((?:[^"\\]|\\.)*)"\)')
PROPERTY_RE = re.compile(r'\(property "(Reference|Value|Footprint)" "((?:[^"\\]|\\.)*)"')
INSTANCE_REF_RE = re.compile(r'\(reference "((?:[^"\\]|\\.)*)"\)')
PAPER_RE = re.compile(r'\(paper\s+"([^"]+)"((?:\s+[-\d.]+){0,2})(\s+portrait)?\s*\)')

# Landscape sizes in mm, as KiCad defines them.
PAPERS = {
    "A5": (210, 148), "A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594),
    "A0": (1189, 841), "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
    "D": (863.6, 558.8), "E": (1117.6, 863.6), "USLetter": (279.4, 215.9),
    "USLegal": (355.6, 215.9), "USLedger": (431.8, 279.4),
}
UPGRADES = ["A4", "A3", "A2", "A1", "A0"]


# ---------------------------------------------------------------- sheet file

def top_level_items(text: str) -> list[tuple[int, int]]:
    """Spans (start, end) of the direct children of the root (kicad_sch ...) list."""
    spans, depth, start, i, in_str = [], 0, 0, 0, False
    while i < len(text):
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
                start = i
        elif c == ")":
            if depth == 2:
                spans.append((start, i + 1))
            depth -= 1
        i += 1
    return spans


def own_items(text: str) -> list[tuple[int, int, str]]:
    found = []
    for s, e in top_level_items(text):
        item = text[s:e]
        if OWN_GRAPHIC_RE.match(item):
            found.append((s, e, "line"))
        elif OWN_TEXT_RE.match(item):
            found.append((s, e, "name"))
    return found


def strip_own(text: str) -> tuple[str, int]:
    items = own_items(text)
    for s, e, _ in reversed(items):
        # Also drop the indentation before the item and the newline after it.
        while s > 0 and text[s - 1] in " \t":
            s -= 1
        if text[e:e + 1] == "\n":
            e += 1
        text = text[:s] + text[e:]
    return text, len(items)


def paper_size(text: str, override: str | None) -> tuple[str, float, float]:
    if override:
        name, w, h, portrait = override, None, None, False
    else:
        m = PAPER_RE.search(text)
        if not m:
            raise SystemExit("error: no (paper ...) in the sheet")
        name, dims, portrait = m.group(1), m.group(2).split(), bool(m.group(3))
        if name == "User" and len(dims) == 2:
            return name, float(dims[0]), float(dims[1])
    if name not in PAPERS:
        raise SystemExit(f"error: unknown paper size {name!r}")
    w, h = PAPERS[name]
    return name, *((h, w) if portrait else (w, h))


def frame(paper_w: float, paper_h: float, args) -> tuple[tuple, tuple | None]:
    fx1, fy1, fx2, fy2 = args.inset, args.inset, paper_w - args.inset, paper_h - args.inset
    tw, th = args.title_block
    title = (fx2 - tw, fy2 - th, fx2, fy2) if tw > 0 and th > 0 else None
    return (fx1, fy1, fx2, fy2), title


# ---------------------------------------------------------------- plan

def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 2)


def snap_up(v: float) -> float:
    return round(math.ceil(round(v / GRID, 6)) * GRID, 2)


def pack(modules: list[dict], width: float, pad: float) -> list[list[dict]]:
    """Shelf packing in the given order; each row is a list of modules."""
    rows, row, used = [], [], 0.0
    for m in modules:
        need = need_w(m, pad)
        if row and used + need > width:
            rows.append(row)
            row, used = [], 0.0
        row.append(m)
        used += need
    if row:
        rows.append(row)
    return rows


# One extra grid step absorbs snapping the region borders and the content corner to the grid.
def need_w(m: dict, pad: float) -> float:
    return m["w"] + 2 * pad + GRID


def need_h(m: dict, pad: float) -> float:
    return m["h"] + 2 * pad + NAME_BAND + GRID


def fits(modules: list[dict], fw: float, fh: float, pad: float) -> bool:
    if any(need_w(m, pad) > fw for m in modules):
        return False
    return sum(max(need_h(m, pad) for m in row) for row in pack(modules, fw, pad)) <= fh


def plan(modules: list[dict], fr: tuple, title: tuple | None, pad: float) -> dict:
    fx1, fy1, fx2, fy2 = fr
    fw, fh = fx2 - fx1, fy2 - fy1
    rows = pack(modules, fw, pad)
    heights = [max(need_h(m, pad) for m in row) for row in rows]
    # Stretch rows to fill the frame height, regions to fill each row's width.
    extra_h = max(0.0, fh - sum(heights)) / len(rows)
    regions, y = [], fy1
    for r, (row, h) in enumerate(zip(rows, heights)):
        y_next = fy2 if r == len(rows) - 1 else max(snap(y + h + extra_h), snap_up(y + h))
        widths = [need_w(m, pad) for m in row]
        extra_w = max(0.0, fw - sum(widths)) / len(row)
        x = fx1
        for i, (m, w) in enumerate(zip(row, widths)):
            x_next = fx2 if i == len(row) - 1 else max(snap(x + w + extra_w), snap_up(x + w))
            regions.append({
                "name": m["name"], "x1": x, "y1": y, "x2": x_next, "y2": y_next,
                "place_x": snap_up(x + pad), "place_y": snap_up(y + pad + NAME_BAND),
                "w": m["w"], "h": m["h"],
            })
            x = x_next
        y = y_next
    warnings = []
    for r in regions:
        content = (r["place_x"], r["place_y"], r["place_x"] + r["w"], r["place_y"] + r["h"])
        if title and intersects(content, title):
            warnings.append(f"{r['name']}: content would cover the title block; put a smaller module last "
                            f"or keep the bottom-right {title[2] - title[0]:g}x{title[3] - title[1]:g} mm free")
    return {"frame": list(fr), "title_block": list(title) if title else None,
            "regions": regions, "warnings": warnings}


def grid_plan(modules: list[dict], fr: tuple, title: tuple | None, pad: float,
              cols: int, rows: int) -> dict:
    fx1, fy1, fx2, fy2 = fr
    xs = [fx1] + [snap(fx1 + (fx2 - fx1) * i / cols) for i in range(1, cols)] + [fx2]
    ys = [fy1] + [snap(fy1 + (fy2 - fy1) * j / rows) for j in range(1, rows)] + [fy2]
    cells = [(xs[i], ys[j], xs[i + 1], ys[j + 1]) for j in range(rows) for i in range(cols)]
    if len(cells) < len(modules):
        raise ValueError(f"{len(modules)} modules do not fit in a {cols}x{rows} grid")
    spare = len(cells) - len(modules)
    empty = []
    for c in reversed(cells):   # the title block sits in the bottom-right corner
        if spare and title and intersects(c, title):
            empty.append(c)
            spare -= 1
    used = [c for c in cells if c not in empty][:len(modules)]
    empty += [c for c in cells if c not in empty and c not in used]
    regions, warnings, fits_all = [], [], True
    for m, (x1, y1, x2, y2) in zip(modules, used):
        r = {"name": m["name"], "x1": x1, "y1": y1, "x2": x2, "y2": y2,
             "place_x": snap_up(x1 + pad), "place_y": snap_up(y1 + pad + NAME_BAND), "w": m["w"], "h": m["h"]}
        if need_w(m, pad) > x2 - x1 or need_h(m, pad) > y2 - y1:
            fits_all = False
            warnings.append(f"{m['name']}: {m['w']:g}x{m['h']:g} mm does not fit a "
                            f"{x2 - x1:g}x{y2 - y1:g} mm cell with its padding")
        content = (r["place_x"], r["place_y"], r["place_x"] + r["w"], r["place_y"] + r["h"])
        if title and intersects(content, title):
            warnings.append(f"{m['name']}: content would cover the title block")
        regions.append(r)
    return {"fits": fits_all, "frame": list(fr), "title_block": list(title) if title else None,
            "regions": regions, "empty_cells": [list(c) for c in empty], "warnings": warnings}


# ---------------------------------------------------------------- draw

def intersects(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def cut(interval: tuple[float, float], hole: tuple[float, float]) -> list[tuple[float, float]]:
    a, b = interval
    h1, h2 = hole
    if h2 <= a or h1 >= b:
        return [interval]
    return [p for p in ((a, h1), (h2, b)) if p[1] - p[0] > 1e-6]


def borders(regions: list[dict], fr: tuple, title: tuple | None) -> list[tuple]:
    """Merged region edges that are not on the frame, clipped at the title block."""
    fx1, fy1, fx2, fy2 = fr
    horiz: dict[float, list] = {}
    vert: dict[float, list] = {}
    for r in regions:
        for y in (r["y1"], r["y2"]):
            if abs(y - fy1) > 1e-6 and abs(y - fy2) > 1e-6:
                horiz.setdefault(round(y, 3), []).append((r["x1"], r["x2"]))
        for x in (r["x1"], r["x2"]):
            if abs(x - fx1) > 1e-6 and abs(x - fx2) > 1e-6:
                vert.setdefault(round(x, 3), []).append((r["y1"], r["y2"]))
    lines = []
    for y, spans in horiz.items():
        for a, b in merge(spans):
            parts = cut((a, b), (title[0], title[2])) if title and title[1] < y < title[3] else [(a, b)]
            lines += [(p, y, q, y) for p, q in parts]
    for x, spans in vert.items():
        for a, b in merge(spans):
            parts = cut((a, b), (title[1], title[3])) if title and title[0] < x < title[2] else [(a, b)]
            lines += [(x, p, x, q) for p, q in parts]
    return lines


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def polyline(x1: float, y1: float, x2: float, y2: float) -> str:
    return (
        f"\t(polyline\n\t\t(pts\n\t\t\t(xy {x1:g} {y1:g}) (xy {x2:g} {y2:g})\n\t\t)\n"
        f"\t\t(stroke\n\t\t\t(width 0.254)\n\t\t\t(type dash)\n\t\t\t{COLOR}\n\t\t)\n"
        f"\t\t(uuid \"{uuid.uuid4()}\")\n\t)\n"
    )


def name_text(name: str, x: float, y: float) -> str:
    return (
        f"\t(text {quote(name)}\n\t\t(exclude_from_sim no)\n\t\t(at {x:g} {y:g} 0)\n"
        f"\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 2.032 2.032)\n\t\t\t\t(bold yes)\n\t\t\t\t{COLOR}\n\t\t\t)\n"
        f"\t\t\t(justify left top)\n\t\t)\n\t\t(uuid \"{uuid.uuid4()}\")\n\t)\n"
    )


def check(regions: list[dict], fr: tuple) -> list[str]:
    problems = []
    for r in regions:
        if r["x1"] < fr[0] - 1e-6 or r["y1"] < fr[1] - 1e-6 or r["x2"] > fr[2] + 1e-6 or r["y2"] > fr[3] + 1e-6:
            problems.append(f"OUTSIDE {r['name']} leaves the frame {fr}")
    for i, a in enumerate(regions):
        for b in regions[i + 1:]:
            if intersects((a["x1"], a["y1"], a["x2"], a["y2"]), (b["x1"], b["y1"], b["x2"], b["y2"])):
                problems.append(f"OVERLAP {a['name']} <-> {b['name']}")
    return problems


def load_regions(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    regions = data["regions"] if isinstance(data, dict) else data
    out = []
    for i, r in enumerate(regions):
        try:
            x1, x2 = sorted((float(r["x1"]), float(r["x2"])))
            y1, y2 = sorted((float(r["y1"]), float(r["y2"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"error: region {i} in {path}: needs numeric x1, y1, x2, y2 ({exc})")
        out.append({"name": str(r.get("name", "")), "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return out


# ---------------------------------------------------------------- parts

def unquote(s: str) -> str:
    return re.sub(r"\\(.)", r"\1", s)


def region_names(text: str) -> list[tuple[str, float, float]]:
    out = []
    for s, e, kind in own_items(text):
        if kind == "name":
            item = text[s:e]
            x, y = TEXT_AT_RE.search(item).groups()
            out.append((unquote(TEXT_NAME_RE.match(item).group(1)[1:-1]), float(x), float(y)))
    return out


def region_at(text: str, px: float, py: float, fr: tuple) -> tuple:
    """Rectangle bounded by the nearest region lines (or the frame) around the point."""
    x1, y1, x2, y2 = fr
    for s, e, kind in own_items(text):
        if kind != "line":
            continue
        pts = [(float(x), float(y)) for x, y in XY_RE.findall(text[s:e])]
        (ax, ay), (bx, by) = pts[0], pts[-1]
        if abs(ax - bx) < 1e-6 and min(ay, by) <= py <= max(ay, by):
            if ax < px:
                x1 = max(x1, ax)
            else:
                x2 = min(x2, ax)
        elif abs(ay - by) < 1e-6 and min(ax, bx) <= px <= max(ax, bx):
            if ay < py:
                y1 = max(y1, ay)
            else:
                y2 = min(y2, ay)
    return x1, y1, x2, y2


def symbols(text: str) -> list[dict]:
    out = []
    for s, e in top_level_items(text):
        item = text[s:e]
        at = SYMBOL_AT_RE.match(item)
        lib = LIB_ID_RE.search(item)
        if not at or not lib:
            continue
        props = {k: unquote(v) for k, v in PROPERTY_RE.findall(item)}
        ref = props.get("Reference", "")
        if ref.startswith("#") or unquote(lib.group(1)).startswith("power:"):
            continue
        refs = sorted({unquote(r) for r in INSTANCE_REF_RE.findall(item)} - {ref})
        out.append({"ref": ref, "value": props.get("Value", ""), "footprint": props.get("Footprint", ""),
                    "lib_id": unquote(lib.group(1)), "x": float(at.group(1)), "y": float(at.group(2)),
                    **({"instance_refs": refs} if refs else {})})
    return out


def natural(ref: str) -> tuple:
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", ref))


def find_parts(target: Path, name: str, args) -> int:
    sheets = sorted(target.rglob("*.kicad_sch")) if target.is_dir() else [target]
    found = []
    for sheet in sheets:
        text = sheet.read_text()
        found += [(sheet, text, n, x, y) for n, x, y in region_names(text)]
    matches = [f for f in found if f[2] == name] \
        or [f for f in found if f[2].lower() == name.lower()] \
        or [f for f in found if name.lower() in f[2].lower()]
    if len(matches) != 1:
        print(f"error: {'no' if not matches else len(matches)} region(s) named {name!r}", file=sys.stderr)
        for sheet, _, n, _, _ in (matches or found):
            print(f"  {n}  ({sheet})", file=sys.stderr)
        return 2
    sheet, text, n, tx, ty = matches[0]
    _, pw, ph = paper_size(text, None)
    fr, _ = frame(pw, ph, args)
    rect = region_at(text, tx + 0.5, ty + 0.5, fr)
    # The units of a multi-unit part are separate symbols with one reference: list it once.
    by_ref: dict[str, dict] = {}
    for p in symbols(text):
        x, y = p.pop("x"), p.pop("y")
        if rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]:
            by_ref.setdefault(p["ref"], p)
    parts = sorted(by_ref.values(), key=lambda p: natural(p["ref"]))
    print(json.dumps({"sheet": str(sheet), "name": n, "region": list(rect), "parts": parts},
                     ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["plan", "draw", "list", "remove", "parts"])
    ap.add_argument("sheet", type=Path)
    ap.add_argument("data", nargs="?", help="plan: MODULES.json, draw: REGIONS.json, parts: region name")
    ap.add_argument("--pad", type=float, default=5.08)
    ap.add_argument("--paper", help="plan for this paper size instead of the sheet's")
    ap.add_argument("--grid", help="plan: equal cells, COLSxROWS (e.g. 2x3)")
    ap.add_argument("--inset", type=float, default=12.0)
    ap.add_argument("--title-block", default="108x32",
                    type=lambda s: tuple(float(v) for v in s.lower().split("x")))
    args = ap.parse_args()

    if args.action == "parts":
        if args.data is None:
            ap.error("parts needs a region name")
        return find_parts(args.sheet, args.data, args)

    text = args.sheet.read_text()
    if not text.lstrip().startswith("(kicad_sch"):
        print(f"error: {args.sheet} is not a KiCad schematic", file=sys.stderr)
        return 2

    if args.action == "list":
        for s, e, kind in own_items(text):
            item = text[s:e]
            if kind == "line":
                print("line  " + " - ".join(f"({x}, {y})" for x, y in XY_RE.findall(item)))
            else:
                print(f"name  {TEXT_NAME_RE.match(item).group(1)}")
        return 0

    if args.action == "remove":
        text, n = strip_own(text)
        args.sheet.write_text(text)
        print(f"removed {n} item(s) from {args.sheet}")
        return 0

    if args.data is None:
        ap.error(f"{args.action} needs a JSON file")
    paper, pw, ph = paper_size(text, args.paper)
    fr, title = frame(pw, ph, args)

    if args.action == "plan":
        modules = [{"name": str(m["name"]), "w": float(m["w"]), "h": float(m["h"])}
                   for m in json.loads(Path(args.data).read_text())]
        if not modules:
            ap.error("no modules")
        if args.grid:
            try:
                cols, rows = (int(v) for v in args.grid.lower().split("x"))
                result = {"paper": paper, **grid_plan(modules, fr, title, args.pad, cols, rows)}
            except ValueError as exc:
                ap.error(f"--grid {args.grid}: {exc}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["fits"] else 1
        fw, fh = fr[2] - fr[0], fr[3] - fr[1]
        if not fits(modules, fw, fh, args.pad):
            bigger = next((p for p in UPGRADES
                           if fits(modules, PAPERS[p][0] - 2 * args.inset, PAPERS[p][1] - 2 * args.inset, args.pad)),
                          None)
            print(json.dumps({"fits": False, "paper": paper, "fits_on": bigger}, ensure_ascii=False, indent=2))
            return 1
        result = {"fits": True, "paper": paper, **plan(modules, fr, title, args.pad)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    regions = load_regions(Path(args.data))
    text, removed = strip_own(text)
    lines = borders(regions, fr, title)
    new = "".join(polyline(*l) for l in lines) + "".join(
        name_text(r["name"], r["x1"] + 1.27, r["y1"] + 1.27) for r in regions if r["name"])
    end = text.rstrip().rfind(")")
    text = text[:end].rstrip("\n\t ") + "\n" + new + ")\n"
    args.sheet.write_text(text)
    print(f"{args.sheet}: removed {removed} old item(s), drew {len(lines)} line(s) "
          f"and {sum(1 for r in regions if r['name'])} name(s) for {len(regions)} region(s)")
    problems = check(regions, fr)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
