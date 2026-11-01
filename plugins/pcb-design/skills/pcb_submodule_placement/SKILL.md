---
name: pcb_submodule_placement
description: Place one schematic sub-module on the KiCad PCB through the Konnect MCP. The sub-module is a region of the schematic named by blue text in its top-left corner (as drawn by sch_organize); its core part (chip or interface) goes on the requested layer (top or bottom), the module's parts are kept close together, decoupling capacitors go on the opposite layer with the lowest power/ground loop inductance, filter capacitors stay on the core's layer, then capacitors are lined up and silkscreen overlaps removed. Electrical performance, signal/power integrity and manufacturability always come before looks; verified placements are kept. Use when the user asks to place, lay out or arrange a sub-circuit/sub-module/block on the PCB, on the top or bottom side.
argument-hint: "<sub-module name> <top|bottom>"
---

# Place a schematic sub-module on the PCB

Arguments passed to this skill (empty if none): `$ARGUMENTS`

- the **sub-module name**: everything except the last word. It is the blue name text in the
  top-left corner of a region of the schematic (the regions `sch_organize` draws);
- the **core layer**, the last word: `top` / `front` / `F.Cu` (or the Chinese word for top layer) → F.Cu,
  `bottom` / `back` / `B.Cu` (or the Chinese word for bottom layer) → B.Cu.

Ask for whatever is missing. Only parts of this sub-module are moved; every other footprint, and
any footprint locked in KiCad, stays where it is. No tracks are routed.

The priorities below override every step of this skill: where a step's rule (positions, rows,
orientation, silkscreen) conflicts with them, the priorities win and the report says which goal
was not met.

`S` below is `${CLAUDE_PLUGIN_ROOT}/skills/pcb_submodule_placement/scripts`.

All board work goes through the Konnect MCP tools. Load the toolsets first: `load_toolset` with
`["pcb_components", "placement", "pcb_board", "verification", "pcb_export"]`.

## PCB placement priorities

PCB component placement must follow this basic principle:

**Electrical correctness, signal integrity, power integrity and manufacturability always take precedence
over visual appearance.**

Visual goals such as neat rows, consistent orientation and non-overlapping silkscreen must never be
achieved at the cost of electrical performance.

### 1. Decoupling capacitors

- Before placement, identify the power net and the target IC of every decoupling capacitor.
- For critical high-frequency decoupling capacitors, the primary goal is to minimise the parasitic
  inductance of the power/ground loop.
- Take the actual power pads, ground pads, vias, power-plane connections and BGA fanout routing
  constraints into account.
- Never judge a decoupling capacitor's placement only by the distance between the capacitor's centre and
  the IC's centre.
- Keep decoupling placements that have already been verified, unless there is a clear engineering reason
  to change them.
- Never move a decoupling capacitor to an electrically worse position just to make rows neater,
  orientations uniform or the silkscreen better.
- When several ICs share the same power net, do not assign decoupling capacitors by net name alone;
  analyse the schematic's functional grouping and the physical layout.

### 2. General placement

- Place the electrically sensitive critical parts first.
- Group parts by functional block, e.g. FPGA, DDR, clocks, power, communication interfaces and high-speed
  data interfaces.
- During placement, give priority to signal paths, power connections and actual routability.
- Only once the electrical constraints are met, optimise orientation, alignment and visual symmetry.
- Never change a verified placement of critical parts such as FPGAs, DDR, high-speed transceiver parts and
  clock chips just for looks.

### 3. Silkscreen

- Resolve silkscreen overlaps first by moving or rotating the reference designators independently.
- Never move well-placed parts just to avoid silkscreen overlaps.
- Silkscreen must not cover exposed pads or affect soldering and manufacturing.
- Where appropriate, some designators may be kept on the fabrication layer only, instead of showing all of
  them on the silkscreen.
- On dense FPGA boards, allow a uniform, simplified designator scheme for some parts instead of forcing a
  complete silkscreen label around every part.
- Silkscreen optimisation comes only after the electrical placement of the critical parts is finished.

### 4. Placement verification

- Run KiCad DRC after every batch of placement changes.
- Check for new part spacing, pad spacing, board-edge clearance and other design-rule violations.
- Check that no critical part has moved without authorisation.
- For decoupling capacitors, check the power net, target IC, position and possible power/ground loop
  problems.
- Mark electrical issues that cannot be verified automatically as needing manual review.
- Never treat a passing DRC as passing signal-integrity or power-integrity verification.

### 5. Execution order

Optimise the placement in this order:

1. Meet the electrical and manufacturability constraints.
2. Optimise the critical decoupling capacitors and their power/ground connections.
3. Ensure sensible relative positions between critical parts.
4. Ensure routability; do not block high-speed signals.
5. Optimise the arrangement, spacing and orientation of ordinary parts.
6. Finally, optimise silkscreen positions and the overall appearance.

**Key rule: lower-priority visual optimisation must never break higher-priority electrical placement
constraints.**

If not all requirements can be met at once, electrical performance comes first, and the report must state
clearly which visual goals were not met.

## 1. Find the sub-module and its parts

1. The KiCad project: from the conversation or `get_project_info`; ask if unclear.
2. `python3 ${CLAUDE_PLUGIN_ROOT}/skills/sch_organize/scripts/sch_regions.py parts <project dir> "<name>"`
   prints the sheet, the region and its parts (reference, value, footprint). An inexact name is
   matched ignoring case or as a substring; exit 2 lists the candidates: ask the user which one.
   A sheet used by several sheet instances lists `instance_refs`: ask which instance to place.
3. `get_component_list`: every part must be on the board. Missing parts mean the board is not
   in sync with the schematic: run `update_pcb_from_schematic` as a dry run, show the result and
   apply it only with the user's consent.
4. **Baseline**: keep the `get_component_list` result (position, rotation, layer of every
   footprint) and run DRC once; later checks compare against both.
5. `snapshot_project` before moving anything. If the board is open in KiCad, Konnect edits it live
   (undoable there; remind the user to save); otherwise it edits the closed file.

## 2. Classify the parts

Read each part's pads and nets with `get_component_pads`.

- **Core**: the module's chip, or its interface (connector) when the module has no chip. Several
  chips: the one the others serve is the core; the others are placed like "other parts" beside
  it, on the core's layer.
- **Critical parts**: parts whose placement drives electrical performance: FPGA, DDR, high-speed
  transceivers and their parts, clock chips and crystals, switching regulator power stages,
  high-frequency decoupling capacitors. They are placed first.
- **Power pins**: core pads on a power rail (a net carried by power symbols or named like a
  supply, e.g. `+3V3`, `VDD_*`, `VCCIO`), not ground.
- **Decoupling capacitors**: one pad on a rail that feeds a core power pin, the other on
  ground, nothing in between, usually small values (≤ 1 µF: 100 nF, 10 nF, 1 µF). Their target
  IC is the chip of this sub-module (the schematic region), not just any IC on the same net: when
  several ICs share the rail, decide from the schematic grouping and the physical layout, and ask
  if it stays unclear. Pair each with a power pin of its rail: one per pin where possible, the
  smallest value at the pin that needs it most (highest frequency); when there are more
  capacitors than pins, spread them over the pins of that rail.
- **Filter capacitors**: every other capacitor: bulk capacitors on a rail (typically
  ≥ 4.7 µF), regulator input/output capacitors, capacitors in RC/LC/π filters and behind ferrite
  beads, on signal lines, crystal load, feedback/compensation, bootstrap capacitors.
- **Other parts**: resistors, inductors, ferrite beads, diodes/LEDs, transistors, crystals,
  connectors, ...
- **Already placed**: parts of the module that already sit at a deliberate position on the
  board (inside the outline at their IC, locked, or placed by the user). Decoupling capacitors
  and critical parts among them count as **verified and stay where they are**, unless the user
  gives an engineering reason to move them; the plan lists them as "keep".

Through-hole, tall or polarised bulk capacitors (electrolytic, large tantalum) cannot go to the
opposite layer: keep them on the core's layer and say so. A capacitor whose role is unclear
(e.g. 2.2–4.7 µF directly at a power pin) is asked about.

Show the plan as a table (part, value, role, target IC and power pin, target layer, keep/move)
and **wait for the user's confirmation** before moving anything.

## 3. Place

Work in the execution order (section 5 of the priorities above); a later step never moves a part
placed by an earlier one to an electrically worse position. All positions in board millimetres on
a 0.1 mm (or 0.05 mm for fine-pitch) grid; rotations in multiples of 90° unless the core is
rotated otherwise.

1. **Where.** Keep the core where it is if it is inside the board outline (`get_board_extents`)
   and not overlapping other modules' parts. Otherwise ask the user for a location, or propose a
   free area of the board large enough for the module.
2. **Core** on the requested layer: `flip_component` if it is on the other one.
3. **Decoupling capacitors** on the opposite layer (`flip_component`), placed for the smallest
   power/ground loop inductance, judged from the actual pads, not from part centres: the
   capacitor's rail pad as close as possible to the IC power pad (or its via), its ground pad
   as close as possible to the nearest IC ground pad (or its via), so that the loop power pad →
   via → capacitor → via → ground pad is short and both vias sit next to each other. Take the
   existing vias, the power/ground plane connections and, for a BGA, the fanout (`plan_bga_fanout`
   shows where the vias go) into account; do not block the fanout or the escape routing. Keep
   them off the area behind the core's exposed/thermal pad (its via field), and do not let their
   courtyards overlap each other or other opposite-layer parts. The highest-frequency (smallest)
   capacitors get the best positions.
4. **Critical relative positions**: crystals and clock parts within a few mm of their pins,
   switching regulator input capacitor, switch node and inductor in a tight loop, termination and
   series resistors of fast signals at the right end of the line.
5. **Routability**: keep escape channels for the core's high-speed signals and fanout open; no
   part in the way of a differential pair or a memory bus leaving the core.
6. **Filter capacitors** on the core's layer, close to what they filter: bulk capacitors at the
   rail's entry into the module, regulator input/output capacitors at those pins, filter
   networks at the pin they feed, crystal load capacitors next to the crystal.
7. **Other parts** on the core's layer, next to the core pin they connect to: series resistors at
   the driving pin, pull-ups/pull-downs and strap resistors at their pin, ESD protection right at
   the connector, feedback dividers at the feedback pin. Keep the module compact, about 0.5 mm
   courtyard to courtyard, and in signal-flow order.
8. **Line up the capacitors** (both layers), only where it does not make any of 3–7 worse:
   - capacitors form rows: the decoupling capacitors behind each side of the core one row
     parallel to that side; filter capacitors one row or column beside the pins they serve;
   - within a row: the same rotation, the pads the same way round (rail pad towards the core or
     its rail, ground pad on the same side for every capacitor), centres on one line, the same
     pitch (courtyard to courtyard at least 0.25 mm, usually 0.5 mm); decoupling capacitors in the
     order of the power pins along the side, filter capacitors by value with the smallest nearest
     the pin; capacitors of the same package next to each other, mixed packages aligned on their
     centre line;
   - a decoupling capacitor never leaves its electrically best position for a row: it may move
     along the row only if its loop does not get longer; otherwise it stays where it is and the
     row is left imperfect (reported).
   Verified ("keep") parts are not moved to line them up.
9. **Room for the silkscreen**: leave each part's outline clear of its neighbours' (the courtyard
   gap above is usually enough) and about 1 mm beside each row for the reference texts, where
   this costs nothing electrically.
10. **Apply in batches, DRC after each**: (a) all `flip_component` calls; (b) one
    `set_component_placements` call for the core, decoupling capacitors and critical parts;
    (c) one for the remaining parts and the line-up. Run DRC after each batch and fix new
    violations before the next. `align_components`, `move_component` / `rotate_component` only
    for corrections afterwards.
11. **Reference designators**, last, after the electrical placement is final. Silkscreen must
    not overlap other silkscreen, cover exposed pads or cross the board edge; it is fixed by
    moving or rotating the reference texts, never by moving parts that are placed well. The
    script works on the file: if the board is open in KiCad, ask the user to save and close it
    first. Then

    ```bash
    python3 S/silk_refs.py <board.kicad_pcb> <every reference of the module>
    ```

    moves each reference text around its part (above, below, right, left; horizontal, then
    vertical; down to 0.8 mm text) until KiCad's DRC finds no silkscreen violation on it. The
    silkscreen checks are enabled for this even if the project ignores them; footprints are not
    moved. Each run takes a few DRC passes (seconds each). Exit 1 lists the references still in
    conflict and `OTHER` lines for part outlines or other parts' texts touching the module.
    Then, with the user's consent:
    - keep the remaining references on the fabrication layer only: run again with
      `--fab-unresolved` (they move to F.Fab / B.Fab);
    - on a dense board (e.g. under an FPGA), a uniform simplified scheme instead of a text at
      every part, e.g. the references of a capacitor row on the fabrication layer and one
      silkscreen label for the row;
    - only if neither is acceptable, give those parts a little more room, and only if that does
      not affect their electrical placement.

## 4. Verify

DRC passing does not mean signal or power integrity is verified; say so in the report.

1. DRC (verification toolset) compared with the baseline: no new clearance, pad-to-pad,
   courtyard, board-edge or other rule violations. The silkscreen result is the last output of
   `silk_refs.py` (it checks silkscreen even when the project ignores it).
2. **Unauthorised moves**: compare `get_component_list` with the baseline. Only the module's
   parts that the plan moves may have changed; a changed footprint outside the plan, or a "keep"
   part that moved, is reported and put back.
3. `score_placement`: no courtyard overlap and no part outside the outline involving the
   module's parts (deductions caused by other parts are reported, not fixed). On a board whose
   outline is not a plain rectangle (e.g. circular) it reports `outline_unproven` and cannot check
   containment: rely on DRC for parts outside the outline.
4. **Decoupling capacitors**: for each, its rail, target IC and power pin, layer and position,
   and the pad-to-pad distances (`get_pad_position`): capacitor rail pad to the IC power pad and
   capacitor ground pad to the nearest IC ground pad. Flag long loops, a capacitor whose vias
   cannot sit next to each other, or one cut off from its pins by the fanout. Loop inductance,
   via placement and plane connections cannot be verified here: list them as **needs manual
   review**.
5. Capacitor rows: for each row, the largest deviation of a centre from the row line, whether all
   rotations agree, and the pitch; deviations kept for electrical reasons are reported, not fixed.
6. Look at it: export the silkscreen, courtyard and fabrication layers of both sides as SVG
   (`pcb_export`) or `get_board_2d_view` (top side only), and check the module is compact, the
   decoupling capacitors sit behind their power pins and the reference texts are readable and
   next to their parts.

If the result is unusable, restore the snapshot (or undo in KiCad) and tell the user.

## Report

The module and its core layer; a table of the parts with role, layer, position and keep/moved;
each decoupling capacitor's rail, target IC, power pin and pad distances; the capacitor rows;
reference texts that were shrunk, moved to the fabrication layer or are still in conflict; parts
that could not follow the rules (e.g. a through-hole capacitor kept on the core's layer) and why;
**visual goals not met because of electrical priorities**; items that **need manual review**
(loop inductance, vias, plane connections, signal/power integrity); the `score_placement` and DRC
results, with the note that DRC does not verify SI/PI. If the board is open in KiCad, remind the
user to save it.
