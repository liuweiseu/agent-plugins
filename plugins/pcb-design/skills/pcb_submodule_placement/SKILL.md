---
name: pcb_submodule_placement
description: Place one schematic sub-module on the KiCad PCB through the Konnect MCP. The sub-module is a region of the schematic named by blue text in its top-left corner (as drawn by sch_organize); its core part (chip or interface) goes on the requested layer (top or bottom), the module's parts are kept close together, decoupling capacitors go on the opposite layer with the lowest power/ground loop inductance, filter capacitors stay on the core's layer, then capacitors are lined up and silkscreen overlaps removed. Electrical performance, signal/power integrity and manufacturability always come before looks; verified placements are kept. Use when the user asks to place, lay out or arrange a sub-circuit/sub-module/block on the PCB, on the top or bottom side.
argument-hint: "<sub-module name> <top|bottom>"
---

# Place a schematic sub-module on the PCB

Arguments passed to this skill (empty if none): `$ARGUMENTS`

- the **sub-module name**: everything except the last word. It is the blue name text in the
  top-left corner of a region of the schematic (the regions `sch_organize` draws);
- the **core layer**, the last word: `top` / `顶层` / `F.Cu` / `front` → F.Cu,
  `bottom` / `底层` / `B.Cu` / `back` → B.Cu.

Ask for whatever is missing. Only parts of this sub-module are moved; every other footprint, and
any footprint locked in KiCad, stays where it is. No tracks are routed.

The priorities below override every step of this skill: where a step's rule (positions, rows,
orientation, silkscreen) conflicts with them, the priorities win and the report says which goal
was not met.

`S` below is `${CLAUDE_PLUGIN_ROOT}/skills/pcb_submodule_placement/scripts`.

All board work goes through the Konnect MCP tools. Load the toolsets first: `load_toolset` with
`["pcb_components", "placement", "pcb_board", "verification", "pcb_export"]`.

## PCB 元件布局优先级

PCB 元件布局必须遵循以下基本原则：

**电气性能正确性、信号完整性、电源完整性和可制造性，始终优先于视觉美观。**

元件排列整齐、方向一致、丝印不重叠等视觉优化要求，不得以牺牲电气性能为代价。

### 1. 去耦电容布局（Decoupling Capacitors）

- 在布局之前，必须识别每颗去耦电容所属的电源网络，以及对应的目标 IC。
- 对于关键的高频去耦电容，布局应以尽可能降低电源/地回路的寄生电感为主要目标。
- 必须考虑实际电源焊盘、接地焊盘、过孔、电源平面连接以及 BGA 扇出布线约束。
- 不允许仅根据电容封装中心与 IC 封装中心之间的距离，判断去耦电容布局的优劣。
- 对于已经验证过的去耦电容布局，除非有明确的工程理由，否则应保留原有位置。
- 不允许仅仅为了元件排列整齐、方向统一或改善丝印效果，而将去耦电容移动到电气性能较差的位置。
- 对于共享相同电源网络的多个 IC，不应仅根据网络名称决定去耦电容的归属，需要结合原理图功能分组和物理布局进行分析。

### 2. 一般元件布局（General Placement）

- 优先布局对电气性能敏感的关键元件。
- 按照功能模块对元件进行分组，例如 FPGA、DDR、时钟、电源、通信接口和高速数据接口。
- 在布局过程中，优先考虑信号路径、电源连接和实际布线可实现性。
- 在满足电气约束的前提下，再优化元件方向、排列整齐度和视觉对称性。
- 对于 FPGA、DDR、高速收发器相关器件、时钟芯片等关键器件，不得仅为了视觉美观而改变已经验证的布局。

### 3. 丝印处理（Silkscreen）

- 优先通过独立移动或旋转元件位号（Reference Designator），解决丝印重叠问题。
- 不允许仅仅为了避免丝印重叠而随意移动已经合理布局的元件。
- 丝印不得覆盖裸露焊盘或影响焊接与制造。
- 在适当情况下，可以将部分元件标识保留在制造层（Fabrication Layer），而不要求全部显示在丝印层。
- 对于高密度 FPGA PCB，应允许部分丝印位号采用统一、简化的布局方式，而不是强行要求每个元件周围都有完整丝印。
- 丝印优化必须在关键元件的电气布局完成之后进行。

### 4. 布局验证（Placement Verification）

- 每次完成一批元件布局修改之后，都应运行 KiCad DRC。
- 检查是否出现新的器件间距、焊盘间距、板边距离及其他设计规则违规。
- 检查关键器件位置是否发生未经授权的变化。
- 对于去耦电容，应检查其电源网络、目标 IC、位置以及潜在的电源/地回路问题。
- 对无法自动验证的电气性能问题，应明确标记为需要人工审核。
- 不得将通过 DRC 等同于通过信号完整性或电源完整性验证。

### 5. 布局执行原则

按照以下顺序执行布局优化：

1. 满足电气性能和可制造性约束。
2. 优化关键去耦电容与电源/地连接。
3. 保证关键器件之间合理的相对位置。
4. 保证布线可实现性，避免阻塞高速信号。
5. 优化普通元件的排列、间距和方向。
6. 最后优化丝印位置和整体视觉效果。

**重要规则：低优先级的视觉优化，不得破坏高优先级的电气布局约束。**

如果无法同时满足所有要求，必须优先保证电气性能，并在结果报告中明确说明未满足的视觉优化目标。

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
- **Decoupling capacitors** (去耦电容): one pad on a rail that feeds a core power pin, the other on
  ground, nothing in between, usually small values (≤ 1 µF: 100 nF, 10 nF, 1 µF). Their target
  IC is the chip of this sub-module (the schematic region), not just any IC on the same net: when
  several ICs share the rail, decide from the schematic grouping and the physical layout, and ask
  if it stays unclear. Pair each with a power pin of its rail: one per pin where possible, the
  smallest value at the pin that needs it most (highest frequency); when there are more
  capacitors than pins, spread them over the pins of that rail.
- **Filter capacitors** (滤波电容): every other capacitor: bulk capacitors on a rail (typically
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

Work in the order of the execution priorities (section 5 above); a later step never moves a part
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
