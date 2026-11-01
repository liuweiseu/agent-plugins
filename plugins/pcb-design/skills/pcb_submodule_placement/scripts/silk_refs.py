#!/usr/bin/env python3
"""Move footprint reference designators so that no silkscreen overlaps (pcb_submodule_placement).

    silk_refs.py BOARD.kicad_pcb REF [REF ...] [--min-size MM] [--gap MM] [--fab-unresolved] [--dry-run]

For each given footprint the Reference text on the silkscreen is tried at candidate positions
around the footprint's courtyard: above, below, right, left; horizontal, then vertical; at its
current size, then at --min-size (default 0.8 mm, a common fab minimum). After each round KiCad's
own DRC (kicad-cli) is run on a copy of the board with the silkscreen checks enabled
(silk_overlap, silk_over_copper, silk_edge_clearance), and every reference still involved in a
silkscreen violation moves on to its next candidate. Footprints are never moved, other
footprints' texts are never touched, hidden references are skipped.

--fab-unresolved moves the references still in conflict after every candidate from the
silkscreen to the fabrication layer of their side (F.Fab / B.Fab), so they stay in the
assembly drawings without overlapping on the silkscreen. Use it only with the user's consent.

The board must not be open in KiCad's PCB editor (it would overwrite the file on save).
Other silkscreen violations involving these footprints (their outlines, or other footprints'
texts) cannot be fixed by moving their texts; the new ones (not in the DRC before the run) are
listed as OTHER: the parts need more space, or the other text needs moving.

Exit status: 0 no silkscreen violation left on the given references, 1 some remain (listed),
2 error.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SILK_CHECKS = ("silk_overlap", "silk_over_copper", "silk_edge_clearance")
CHAR_WIDTH = 0.8          # stroke-font advance per character, as a fraction of the text height
SIDES = ("above", "below", "right", "left")
ITEM_REF_RE = re.compile(r"\bof (\S+)")


# ---------------------------------------------------------------- s-expression spans

def children(text: str, start: int = -1) -> list[tuple[int, int]]:
    """Spans of the direct children of the list starting at `start` (-1: the root list)."""
    if start < 0:
        start = text.index("(")
    spans, depth, child, i, in_str = [], 0, 0, start, False
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


def footprints(text: str) -> dict[str, tuple[int, int]]:
    out = {}
    for s, e in children(text):
        if head(text[s:e]) == "footprint":
            m = re.search(r'\(property "Reference" "((?:[^"\\]|\\.)*)"', text[s:e])
            if m:
                out[m.group(1)] = (s, e)
    return out


def reference_span(text: str, fp: tuple[int, int]) -> tuple[int, int] | None:
    for s, e in children(text, fp[0]):
        if text[s:e].startswith('(property "Reference"'):
            return s, e
    return None


# ---------------------------------------------------------------- geometry (footprint-local)

def floats(s: str) -> list[float]:
    return [float(v) for v in s.split()]


def local_bbox(fp_text: str) -> tuple[float, float, float, float] | None:
    """Bounding box of the courtyard (else the pads) in footprint-local coordinates."""
    xs, ys = [], []
    for s, e in children(fp_text, 0):
        item = fp_text[s:e]
        if not re.search(r'\(layer "[FB]\.CrtYd"\)', item) or head(item) not in (
                "fp_line", "fp_rect", "fp_poly", "fp_arc", "fp_circle"):
            continue
        if head(item) == "fp_circle":
            c = floats(re.search(r"\(center ([-\d.]+ [-\d.]+)\)", item).group(1))
            p = floats(re.search(r"\(end ([-\d.]+ [-\d.]+)\)", item).group(1))
            r = ((c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2) ** 0.5
            xs += [c[0] - r, c[0] + r]
            ys += [c[1] - r, c[1] + r]
            continue
        for m in re.finditer(r"\((?:start|end|mid|xy) ([-\d.]+) ([-\d.]+)\)", item):
            xs.append(float(m.group(1)))
            ys.append(float(m.group(2)))
    if not xs:
        for s, e in children(fp_text, 0):
            item = fp_text[s:e]
            if head(item) == "pad":
                at = floats(re.search(r"\(at ([-\d.]+ [-\d.]+)", item).group(1))
                size = floats(re.search(r"\(size ([-\d.]+ [-\d.]+)\)", item).group(1))
                half = max(size) / 2
                xs += [at[0] - half, at[0] + half]
                ys += [at[1] - half, at[1] + half]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def candidates(ref: str, bbox: tuple, fp_rot: float, size: float, min_size: float, gap: float) -> list[dict]:
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    out = []
    for s in dict.fromkeys((size, min(size, min_size))):
        for angle in (0, 90):
            # Text extents in the footprint's own frame: is the text along its local x axis?
            along_x = round((angle - fp_rot) % 180) == 0
            w, h = len(ref) * s * CHAR_WIDTH, s
            ex, ey = (w, h) if along_x else (h, w)
            for side in SIDES:
                x, y = {"above": (cx, y1 - gap - ey / 2), "below": (cx, y2 + gap + ey / 2),
                        "right": (x2 + gap + ex / 2, cy), "left": (x1 - gap - ex / 2, cy)}[side]
                out.append({"side": side, "angle": angle, "size": s, "x": round(x, 3), "y": round(y, 3)})
    return out


# ---------------------------------------------------------------- editing

def reference_to_fab(text: str, ref: str) -> str:
    s, e = reference_span(text, footprints(text)[ref])
    prop = re.sub(r'\(layer "([FB])\.SilkS"\)', r'(layer "\1.Fab")', text[s:e], count=1)
    return text[:s] + prop + text[e:]


def set_reference(text: str, ref: str, c: dict) -> str:
    fp = footprints(text)[ref]
    s, e = reference_span(text, fp)
    prop = text[s:e]
    thickness = round(c["size"] * 0.15, 3)
    prop = re.sub(r"\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)", f"(at {c['x']:g} {c['y']:g} {c['angle']:g})", prop, count=1)
    prop = re.sub(r"\(size [\d.]+ [\d.]+\)", f"(size {c['size']:g} {c['size']:g})", prop, count=1)
    prop = re.sub(r"\(thickness [\d.]+\)", f"(thickness {thickness:g})", prop, count=1)
    # Centre the text on its position; keep only the mirroring of back-side text.
    prop = re.sub(r"\(justify([^)]*)\)",
                  lambda m: "(justify mirror)" if "mirror" in m.group(1).split() else "", prop)
    prop = re.sub(r"\n\s*\n", "\n", prop)
    return text[:s] + prop + text[e:]


# ---------------------------------------------------------------- DRC

def run_drc(text: str, board: Path, work: Path) -> list[dict]:
    pcb = work / board.name
    pcb.write_text(text)
    pro_src = board.with_suffix(".kicad_pro")
    pro = json.loads(pro_src.read_text()) if pro_src.exists() else {}
    sev = pro.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})
    for check in SILK_CHECKS:
        sev[check] = "error"
    pcb.with_suffix(".kicad_pro").write_text(json.dumps(pro, indent=2))
    report = work / "drc.json"
    res = subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
                          "-o", str(report), str(pcb)], capture_output=True, text=True)
    if not report.exists():
        raise RuntimeError(f"kicad-cli pcb drc failed: {res.stderr.strip() or res.stdout.strip()}")
    return [v for v in json.loads(report.read_text())["violations"] if v["type"] in SILK_CHECKS]


def key(v: dict) -> tuple:
    return v["type"], tuple(sorted(i.get("description", "") for i in v.get("items", [])))


def involved(v: dict) -> list[tuple[str, bool]]:
    """(reference, is_reference_text) for every item of a violation."""
    out = []
    for item in v.get("items", []):
        desc = item.get("description", "")
        m = ITEM_REF_RE.search(desc)
        if m:
            out.append((m.group(1).rstrip(".,:;"), desc.startswith("Reference field")))
    return out


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board", type=Path)
    ap.add_argument("refs", nargs="+")
    ap.add_argument("--min-size", type=float, default=0.8)
    ap.add_argument("--gap", type=float, default=0.2, help="courtyard to text, mm")
    ap.add_argument("--fab-unresolved", action="store_true",
                    help="move references still in conflict to the fabrication layer")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not shutil.which("kicad-cli"):
        print("error: kicad-cli is not on PATH", file=sys.stderr)
        return 2
    text = args.board.read_text()
    fps = footprints(text)
    plans, skipped = {}, []
    for ref in args.refs:
        if ref not in fps:
            print(f"error: no footprint {ref} on {args.board}", file=sys.stderr)
            return 2
        fp_text = text[fps[ref][0]:fps[ref][1]]
        prop = text[slice(*reference_span(text, fps[ref]))]
        if "(hide yes)" in prop or not re.search(r'\(layer "[FB]\.SilkS"\)', prop):
            skipped.append(ref)
            continue
        at = re.search(r"\(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)", fp_text)
        size = floats(re.search(r"\(size ([\d.]+) [\d.]+\)", prop).group(1))[0]
        bbox = local_bbox(fp_text)
        if bbox is None:
            skipped.append(ref)
            continue
        plans[ref] = candidates(ref, bbox, float(at.group(1) or 0), size, args.min_size, args.gap)

    choice = {ref: 0 for ref in plans}
    violations: list[dict] = []
    other: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        baseline = {key(v) for v in run_drc(text, args.board, Path(tmp))} if plans else set()
        for ref in plans:
            text = set_reference(text, ref, plans[ref][0])
        while plans:
            violations = run_drc(text, args.board, Path(tmp))
            to_move, other = [], []
            for v in violations:
                items = involved(v)
                texts = [r for r, is_text in items if is_text and r in plans]
                if texts:
                    # Two of our texts clashing: move only the last one, so they do not chase each other.
                    to_move.append(sorted(texts, key=args.refs.index)[-1])
                elif any(r in plans for r, _ in items) and key(v) not in baseline:
                    other.append(f"{v['type']}: " + " / ".join(i.get("description", "") for i in v["items"]))
            to_move = [r for r in dict.fromkeys(to_move) if choice[r] + 1 < len(plans[r])]
            if not to_move:
                break
            for ref in to_move:
                choice[ref] += 1
                text = set_reference(text, ref, plans[ref][choice[ref]])

    left = sorted({r for v in violations for r, is_text in involved(v) if is_text and r in plans},
                  key=args.refs.index)
    fab = left if args.fab_unresolved else []
    for ref in fab:
        text = reference_to_fab(text, ref)
    left = [r for r in left if r not in fab]
    for ref in plans:
        c = plans[ref][choice[ref]]
        state = "moved to Fab layer" if ref in fab else "VIOLATION" if ref in left else "ok"
        print(f"{ref:<8} {c['side']:<6} {c['angle']:>3}° size {c['size']:g}  {state}")
    for ref in skipped:
        print(f"{ref:<8} skipped (hidden, not on silkscreen, or no geometry)")
    for p in dict.fromkeys(other):
        print(f"OTHER   {p}")
    if not args.dry_run:
        args.board.write_text(text)
    print("dry run, nothing written" if args.dry_run else f"updated {args.board}")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
