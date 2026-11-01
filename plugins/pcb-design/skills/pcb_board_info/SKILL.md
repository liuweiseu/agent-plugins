---
name: pcb_board_info
description: Set up a KiCad PCB's mechanical definition from a JSON board spec: board outline (rectangle or circle), mounting holes, copper layer count, board thickness, surface finish and copper-to-edge clearance. Works on a new board or replaces the outline of an existing one. Use when the user gives a board spec JSON or asks to create/resize a board outline, set the board shape or size, add mounting holes, or set the layer count or thickness.
argument-hint: "<board-spec.json> [project or .kicad_pcb]"
---

# Apply a board spec to a KiCad board

Arguments passed to this skill (empty if none): `$ARGUMENTS`: the board spec JSON, optionally
followed by the KiCad project or `.kicad_pcb` to apply it to. Ask for what is missing.

The spec format is in [references/board-spec.md](references/board-spec.md) (bottom-left corner
is (0, 0), y up, millimetres); examples are in `references/examples/`. When the user has no spec
yet, write one with them from that format.

`S` below is `${CLAUDE_PLUGIN_ROOT}/skills/pcb_board_info/scripts`. The script edits the board
file directly, because Konnect cannot draw circular outlines or change the stackup; Konnect is
used for the project, the snapshot and the checks. Load its toolsets first: `load_toolset` with
`["pcb_board", "verification"]`.

## 1. Check the spec

`python3 S/board_info.py check <spec.json>` validates it and prints it in KiCad coordinates.
`invalid: ...` (exit 1): show the problem and fix the spec with the user. Pass `WARNING` lines
(e.g. a hole close to the edge) on to the user.

## 2. Find or create the board

- **Existing board**: the `.kicad_pcb` given, or the one of the given project (`get_project_info`).
- **New board**: with the user's consent, `create_project` (project toolset) in the directory
  they choose, then use its `.kicad_pcb`.

The board must not be open in KiCad's PCB editor while the script runs (it would overwrite the
file on save): ask the user to save and close it. Then `snapshot_project`.

## 3. Apply

1. `python3 S/board_info.py apply <spec.json> <board.kicad_pcb> --dry-run` and show the user what
   will change.
2. If the board already has an outline the script refuses (exit 1). Replacing it is the user's
   decision: confirm, then run with `--replace`. It removes the Edge.Cuts graphics and the
   board-only MountingHole footprints first; mounting holes linked to schematic symbols are kept
   and listed (tell the user; they are changed in the schematic).
3. Run `apply` without `--dry-run` (plus `--replace` when confirmed). Other errors:
   - inner layers still in use when reducing the layer count: refused; tell the user which
     layers carry items and stop;
   - a drill size without a KiCad footprint: the message lists the available sizes; agree on one
     and fix the spec;
   - KiCad's footprint library not found: ask for its directory and pass `--footprint-dir`.

## 4. Verify

1. `get_board_info` / `get_board_extents`: the outline size and position match the spec.
2. `get_layer_list`: the copper layers match `stackup.copper_layers`.
3. DRC (verification toolset). Expect violations from parts that are now outside a smaller
   outline or too close to the edge; report them, but do not move parts unless asked.
4. When the user opens the board in KiCad, `get_board_stackup` (live only) confirms the stackup.

If anything went wrong, restore the snapshot and tell the user.

## Report

The outline (shape, size, KiCad position of the bottom-left corner), each mounting hole
(reference, footprint, spec and KiCad coordinates), the stackup (copper layers, thickness, each
dielectric, finish), the edge clearance, mounting holes kept because they belong to the
schematic, and the DRC summary. Tell the user to reopen the board in KiCad.
