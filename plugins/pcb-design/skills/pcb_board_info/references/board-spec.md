# Board spec (`pcb_board_info` input)

A JSON file describing the mechanical board: outline, mounting holes, stackup and edge clearance.
Examples: [examples/rectangle_4layer.json](examples/rectangle_4layer.json),
[examples/circle_2layer.json](examples/circle_2layer.json).

## Coordinates

- Millimetres only (`"units": "mm"`).
- The board's **bottom-left corner is (0, 0) and y points up**, as on a mechanical drawing. For a
  circle the bottom-left corner of its bounding square is (0, 0), so its centre is (r, r).
- KiCad's y axis points down; the conversion is done by the script. `origin` is where the
  bottom-left corner goes in KiCad coordinates. Default: the board's top-left corner at (100, 100).

## Keys

| key | required | meaning |
|---|---|---|
| `version` | no | `1` |
| `name` | no | board name, for reports |
| `units` | no | `"mm"` |
| `origin` | no | `[x, y]`: KiCad position of the bottom-left corner |
| `outline` | yes | board shape, see below |
| `mounting_holes` | no | list of holes or hole patterns, see below |
| `stackup` | no | copper layers, thickness, finish, see below |
| `edge_clearance` | no | minimum copper-to-board-edge clearance in mm (KiCad board setup rule) |
| `comment` | no | free text, ignored |

Unknown keys are rejected, so typos do not pass silently.

### `outline`

| shape | parameters |
|---|---|
| `rectangle` | `width`, `height` |
| `circle` | `diameter` |

```json
"outline": { "shape": "rectangle", "width": 100, "height": 80 }
"outline": { "shape": "circle", "diameter": 60 }
```

### `mounting_holes`

Each entry is one hole or a pattern of holes. Every hole has `drill` (mm) and optional `plated`
(default `false`; `true` uses KiCad's `_Pad` footprint with an annular ring).

| form | parameters |
|---|---|
| single hole | `at: [x, y]` |
| `"pattern": "corners"` (rectangle) | `inset`: distance from both edges to each of the four hole centres |
| `"pattern": "polar"` (circle) | `count`, `inset` (board edge to hole centre), `start_angle` (degrees, counter-clockwise from +x; default 45) |

`drill` must be a size KiCad's MountingHole library has: 2, 2.1, 2.2, 2.5, 2.7, 3, 3.2 (M3), 3.5,
3.7, 4, 4.3 (M4), 4.5, 5, 5.3 (M5), 5.5, 6, 6.4 (M6), 6.5, 8.4 (M8). Plated holes exist for most
of these; the script lists the available sizes when one is missing.

A hole crossing the board edge or overlapping another hole is an error; a hole closer than
1 mm (or `edge_clearance`) to the edge is a warning.

### `stackup`

| key | meaning |
|---|---|
| `copper_layers` | even, 2 to 32 |
| `thickness` | finished board thickness in mm |
| `finish` | optional surface finish, KiCad's names: `None`, `HAL SnPb`, `HAL lead-free`, `ENIG`, `ENEPIG`, `Hard gold`, `Immersion tin`, `Immersion nickel`, `Immersion silver`, `Immersion gold`, `OSP`, `HT_OSP`, `User defined` |

Copper is 0.035 mm and solder mask 0.01 mm per layer; the dielectrics (alternating core and
prepreg, FR4) share the rest of the thickness equally. Fine-tune them later in KiCad's Board
Setup if the fabricator specifies a stackup.

## Full example

```json
{
  "version": 1,
  "name": "adapter-board",
  "units": "mm",
  "outline": { "shape": "rectangle", "width": 100, "height": 80 },
  "mounting_holes": [
    { "pattern": "corners", "inset": 4, "drill": 3.2 },
    { "at": [50, 74], "drill": 2.7, "plated": true }
  ],
  "stackup": { "copper_layers": 4, "thickness": 1.6, "finish": "ENIG" },
  "edge_clearance": 0.5
}
```
