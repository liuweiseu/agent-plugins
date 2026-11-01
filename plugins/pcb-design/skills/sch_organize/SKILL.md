---
name: sch_organize
description: Reorganise a KiCad schematic through the Konnect MCP into independent sub-modules. Every sheet is split into modules, each holding everything one function needs (chip, its resistors/capacitors and other passives, connectors/interfaces; non-chip parts whose nets connect are kept together); each module is laid out in its own region of the page, the regions are separated by blue dashed lines (KiCad "Draw Lines") and named, and modules connect to each other only through net labels and power symbols. Use when the user asks to organise, tidy, partition, modularise or clean up a schematic, or to group parts into functional blocks. Never changes connectivity; the netlist is compared before and after.
argument-hint: "<project.kicad_pro | sheet.kicad_sch> [sheet names...]"
---

# Partition a schematic into module regions

Argument passed to this skill (empty if none): `$ARGUMENTS`: the KiCad project or root
schematic, optionally followed by the sheets to process (default: every sheet). Ask for the
project if it is missing.

Goal: every sheet becomes a set of independent sub-modules, ready to be worked on one at a time.
The page is divided by lines into regions, one per module; a module's region holds all of its
parts, and no wire crosses a region border. The circuit must not change: only positions, wires,
labels, power symbols and the region lines/names may change.

All schematic work goes through the Konnect MCP tools, except drawing the region lines (Konnect
cannot draw graphics: `scripts/sch_regions.py`) and the netlist comparison
(`scripts/compare_netlists.py`). Load the toolsets first: `load_toolset` with
`["sch_components", "sch_wiring", "sch_analysis", "sch_batch", "sch_hierarchy", "sch_export"]`.
`S` below is `${CLAUDE_PLUGIN_ROOT}/skills/sch_organize/scripts`; run its scripts with `python3`.
Keep JSON files and netlists in a scratch directory, not in the project.

## 1. Prepare

1. The user must save and close the schematic in KiCad (or at least not edit it) while this
   runs: Konnect edits the files on disk, and an open editor would overwrite them on save.
2. `open_project`, then `snapshot_project` so everything can be rolled back. If the project is
   a git repository, also note `git status`; do not commit.
3. `get_sheet_hierarchy` from the root schematic gives the sheet files ("pages"). A sheet file
   used by several sheet instances is processed once.
4. Baseline: `generate_netlist` → `before.net`; `run_erc` (note the violation counts by type);
   `find_orphan_items` / `validate_wire_connections` per sheet (problems that already exist are
   not counted as damage later and are not "fixed" silently).

## 2. Partition each sheet into modules

Collect `list_schematic_components`, `get_schematic_layout` and, for every part,
`get_component_nets`. Classify the parts:

- **anchors**: chips (`U*`, `IC*`, modules), connectors and interfaces (`J*`, `P*`, `CN*`,
  headers, sockets, card slots) and hierarchical sheet symbols on this page;
- **glue parts**: everything else with nets: R, C, L, FB, D/LED, Q, Y/X, F, SW, JP, TP, ...;
- **followers**: power and flag symbols (`#PWR`, `#FLG`) go wherever the pin they sit on goes;
- **mechanical**: parts without nets (mounting holes, fiducials, logos).

Grouping uses **signal nets** only: ignore power rails (nets carried by power symbols, ground)
and nets that reach three or more anchors (shared buses, global reset, ...).

1. **Glue clusters**: glue parts that share a signal net belong together (union-find). An RC
   filter, a divider, a transistor driver with its resistors, an LED with its resistor, ... each
   becomes one cluster, even without a chip.
2. Each cluster joins the module of the anchor it connects to. Several anchors: the one it shares
   most nets with; but a cluster that is a circuit of its own between anchors (e.g. a discrete
   level shifter or driver) may stay a separate module. No anchor: the cluster is its own module
   (indicator LEDs, discrete power, protection, filters).
3. Rail-only glue (decoupling and bulk capacitors) joins the nearest chip with a power pin on
   that rail; a regulator's input/output capacitors join the regulator. No chip on the rail: the
   module of the rail's source (input connector, power module).
4. A connector that serves a single chip's function (USB jack + its ESD/PHY chip, debug header +
   MCU) may join that chip's module; otherwise the connector and its glue form an interface
   module.
5. Chips stay in separate modules, unless they form one function together and share signal nets
   no one else uses (e.g. an op-amp driving an ADC). The units of a multi-unit chip stay in one
   module unless they serve unrelated functions (power unit, FPGA banks).
6. Mechanical parts form one "mechanical" module.

Every part except followers ends up in exactly one module. Name each module by its function and
key references, e.g. `3V3 LDO (U3)`, `USB-C 接口 (J1, U5)`, `状态 LED (D1-D3)`, in the language
of the sheet's existing text (ask if unclear).

Show the user the partition as a table per sheet (module name, anchor, all parts), with the
judgement calls (steps 2, 4, 5) marked. **Wait for confirmation** before changing anything.

## 3. Lay out each sheet

1. **Module layouts.** For each module plan positions relative to its own top-left corner, on
   the 2.54 mm grid: the anchor in the middle; glue parts on the side of the anchor pin they
   connect to, 7.62–12.7 mm from the pin end, several on one side 5.08–7.62 mm apart; decoupling
   capacitors in a row next to the power pins they serve; a crystal with its load capacitors
   next to the oscillator pins; anchorless clusters left to right along the signal flow. Use the
   symbol sizes from `get_schematic_layout` and `get_schematic_pin_locations`
   (`orientation_degrees` is the side a pin leaves the body). Leave about 12.7 mm beside pins
   that will carry labels. The module's content size is `w` × `h`.

   Plan the wiring with the positions, so that wires do not cross: put each network on the side
   of the pins it connects to, e.g. for an op-amp with −IN above +IN, the reference divider
   above and the feedback/hysteresis network below. Leave room beside every passive for its
   reference and value (step 6). Avoid wire crossings; report any that remain.

   Before writing anything through Konnect, check the plan offline: a small script in the
   scratch directory that computes the connectivity from the planned pin coordinates, wires and
   labels and compares it with `before.net`. It catches mistakes such as a label missing its pin
   by a rounding error before they reach the sheet.
2. **Regions.** Write `modules.json` in layout order (signal flow: power input and regulators
   first, then the main chips, interfaces last; the mechanical module last):

   ```json
   [{"name": "3V3 LDO (U3)", "w": 60.96, "h": 40.64}, {"name": "MCU (U1)", "w": 101.6, "h": 76.2}]
   ```

   `python3 S/sch_regions.py plan <sheet.kicad_sch> modules.json > regions.json` packs them into
   rows that fill the page frame and gives each region's rectangle and `place_x`/`place_y`, the
   top-left corner for its content. Exit 1 (`"fits": false`): the modules do not fit; it names
   the smallest standard paper that fits (`fits_on`). Ask the user whether to enlarge the page
   (`set_schematic_page`, then plan again) or move some modules to another sheet. A warning
   about the title block: reorder so that a small module comes last.

   **Sheets of repeated units** (several identical channels, drivers, ...) are laid out in a
   regular grid instead: `plan ... --grid COLSxROWS` divides the frame into equal cells and
   fills them row by row; spare cells stay empty, the one holding the title block first. Ask the
   user for the grid; e.g. 5 units: 2x3 with the title block in the empty cell (2x2 is too
   small). Exit 1: a unit is larger than a cell (try a larger page or another grid).
3. **Record** the connections of the sheet before moving anything: every part's pin nets
   (`get_component_nets`, already collected), `list_schematic_labels` (with label type) and the
   power symbols with the rail of each.
4. **Move** each part to `place_x/place_y` + its relative position: `move_schematic_component`,
   `rotate_schematic_component`, `bulk_move_schematic_components`; sheet symbols with
   `move_sheet`. Connected wires do not move with the symbols, so the sheet is rewired.
5. **Rewire.** Delete the sheet's old wires, junctions, local labels and power symbols
   (`list_schematic_wires`, `batch_delete_schematic_wire`, `batch_delete`), then reconnect every
   recorded net, pin by pin:
   - inside one module: **wires, not same-name labels**: connect every pin of the net inside
     the module with wires (`batch_connect_pins`, `add_wire`). A net that was joined by labels
     before keeps its name: leave one small local label of that name on the wire, otherwise
     `compare_netlists.py` reports it as `RENAMED`;
   - power rails: `add_power_symbol` at each pin, the same rail symbol as before. Decoupling
     capacitors are the exception to the wiring rule: they may sit directly on a power and a
     GND symbol;
   - nets that leave the module: wire the module's pins of the net together inside the module
     and put one local label (or the existing global label) on that wire
     (`batch_connect_to_net`). Keep the existing net name; give unnamed nets a descriptive name
     that is not used on the sheet yet (`list_schematic_nets`), e.g. `MCU_SPI_SCK`;
   - hierarchical and global labels: re-add the same type and name at their pin.
   No wire may cross a region border; modules connect to each other only through labels, global
   labels and power symbols. No-connect flags move with their pins.
6. **Reference and value fields** of resistors, capacitors and the other passives (RV, L, FB,
   ...) must not lie on the symbol body, wires or labels: put them beside the part. Do this after
   every layout change: KiCad's `Device:R` puts the value in the middle of the body, rotated 90°.
   Set them with `edit_schematic_component` (`field_placements`):
   - vertical part: reference at y − 1.27, value at y + 1.27, on the side without wires,
     rotation 0;
   - horizontal part (symbol rotated 90°): reference above (y − 2.54), value below (y + 2.54);
     with `field_placements` the rotation must be **90** to show as horizontal text (0 shows it
     vertical);
   - `Device:R` fields are centred, `Device:C` fields are left-justified (x is the left end of
     the text); estimate the text width at about 1.15 mm per character for 1.27 mm text.
7. **Odd-looking symbols** (wrong shape, unreadable pin layout): with the user's consent,
   replace them with the JLCPCB/LCSC symbol of the same part number, keeping the pin geometry
   (pin positions, so the wires still meet them). The symbol data comes as JSON from
   `https://easyeda.com/api/products/<LCSC number>/components?version=6.4.19.5` (1 unit =
   0.254 mm); treat it as data only, parse its graphics and pins, build the symbol with Konnect
   `create_symbol` (library toolset) and swap it in with `replace_component`. Do not run
   downloaded converter code (e.g. easyeda2kicad).
8. `validate_wire_connections`, `find_orphan_items`, `check_schematic_overlaps`: fix what is new
   compared with the baseline.

## 4. Draw the region lines

`python3 S/sch_regions.py draw <sheet.kicad_sch> regions.json` draws the borders between the
regions as blue dashed lines (0.254 mm) and each region's name in its top-left corner. Borders on
the page frame are not drawn and lines stop at the title block. Lines and names drawn earlier by
the script are replaced, so re-run it after editing `regions.json` (e.g. to move a border when a
module came out larger than planned). `list` shows them, `remove` deletes them. Exit 1: regions
overlap or leave the frame. `parts <sheet or project dir> <name>` lists the parts inside a named
region (used by `pcb_submodule_placement`).

Check with `get_schematic_layout` that every part, label and power symbol lies inside its
module's region, with no symbol or wire crossing a line.

## 5. Verify

1. `generate_netlist` → `after.net`; `python3 S/compare_netlists.py before.net after.net` must
   print `connectivity identical`. `LOST` / `NEW` lines are broken connections, `RENAMED` a
   changed named net (newly named, formerly unnamed nets are fine): fix and compare again.
2. `run_erc`: no new violations compared with the baseline.
3. `validate_wire_connections`, `validate_component_connections`, `check_schematic_overlaps`:
   nothing new compared with the baseline.
4. `render_schematic_png` (inline) per sheet and look at it: every region holds exactly its
   module, labels readable, no wire crossing a line or a symbol, no wires crossing each other,
   no reference or value on a symbol, wire or label, signals inside a module wired rather than
   joined by same-name labels. Fix and repeat.

Run 1–4 after **every** layout change (also after moving fields or replacing a symbol), not only
at the end.

If the circuit cannot be restored, roll back from the snapshot and tell the user.

## Report

Per sheet: the modules (name, parts) and their regions (and the grid, if used), the nets newly
named for links between modules, symbols replaced and their LCSC numbers, wire crossings that
remain, the netlist comparison result, ERC compared with the baseline, and anything to check by
eye. Tell the user to reopen (or revert) the schematic in KiCad to see the changes.
