# CAID Lite -- CAD Pattern Library

Structured YAML definitions for recurring mechanical CAD constructs.
Each file encodes the preferred CadQuery idiom, anti-patterns to avoid,
required parameters, a short runnable example, and repair hints.

## Directory structure

```
config/patterns/
  <pattern_name>.yaml   -- one file per pattern
  README.md             -- this file
```

## How patterns are used

Pattern files are selected by `PatternSelector` (keyword-based, no LLM call)
and injected into the `DesignerAgent` generation prompt — up to 3 patterns
per request, ranked by keyword overlap with the `DesignPlan`.

Additional planned use:

- **Repair guidance**: `RepairLoop` matches executor error strings against
  `repair_hints` in candidate patterns to produce a targeted repair prompt.

## YAML schema

Each file conforms to this structure:

```
name:         identifier matching the filename (no .yaml)
category:     solid | feature | assembly
purpose:      single-line description
when_to_use:  short paragraph -- when to choose this pattern
idiom:        canonical CadQuery code chain (literal block)
avoid:        list of anti-patterns with brief reason
parameters:   mapping of {name: {type, unit, description}}
example:      complete build_model() function (literal block)
repair_hints: list of actionable repair strings
```

## Pattern index

### Solid primitives

| File | Purpose |
|---|---|
| plate.yaml | Flat rectangular slab; base body for brackets and panels |
| box.yaml | Solid or hollow rectangular enclosure |
| cylinder.yaml | Solid cylinder for shafts, pins, and bosses |
| tube.yaml | Hollow cylinder with concentric through-bore |

### Cut and hole features

| File | Purpose |
|---|---|
| through_hole.yaml | Single circular hole penetrating the full depth |
| blind_hole.yaml | Circular hole terminating at a specified depth |
| slot.yaml | Elongated rounded or rectangular slot cut |
| pocket.yaml | Flat-bottomed rectangular recess |
| hole_pushpoints.yaml | Multiple holes at explicit (x, y) positions |
| hole_rarray.yaml | Uniform rectangular grid of holes |

### Protrusion and edge features

| File | Purpose |
|---|---|
| boss.yaml | Raised cylindrical protrusion on a face |
| fillet.yaml | Rounded edge treatment |
| chamfer.yaml | Angled 45-degree edge break |

### Mechanical assemblies

| File | Purpose |
|---|---|
| l_bracket.yaml | Right-angle structural bracket |
| mounting_block.yaml | Rectangular block with bolt holes for bolted attachment |
| bearing_mount.yaml | Cylindrical housing for rolling-element bearings |
| flange.yaml | Disc with central bore and evenly spaced bolt circle |
| spacer.yaml | Short cylindrical standoff with fastener clearance bore |
| shaft_support.yaml | Base plate with boss for radial shaft alignment and support |
| connector_block.yaml | Block with connector pocket and mounting holes |
| heat_sink.yaml | Heat sink base with parallel fin array (rarray-based) |

## Conventions

- All dimensions in millimeters unless stated otherwise.
- Hole placement always requires `.faces(...).workplane()` before `.hole()`,
  `.pushPoints()`, or `.rarray()`.
- Never use `.eachpoint(lambda loc: cq.Workplane(loc).circle(r), ...)` for
  holes; use `.pushPoints([...]).hole(d)` or `.rarray(...).hole(d)` instead.
- Apply edge features (fillet, chamfer) last, after all cuts and bosses.
