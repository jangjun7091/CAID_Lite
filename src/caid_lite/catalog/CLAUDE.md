# catalog/ — ISO Standard Parts Library

## Purpose
Deterministic CadQuery code generators for ISO/DIN standard parts.
No LLM involved — all geometry is defined by lookup tables in `data.py`.

## Files
- `data.py` — `CATALOG` dict: dimension tables for all supported part types
- `builder.py` — one generator function per part type; returns `build_model()` source string

## CATALOG structure (data.py)
```python
CATALOG: Dict[str, dict] = {
    "iso4762": {          # Socket head cap screw
        "name": "ISO 4762 Socket Head Cap Screw",
        "category": "fastener",   # "fastener" | "bearing" | "shaft" | "profile"
        "sizes": ["M3", "M4", "M5", "M6", "M8", "M10", "M12"],
        "has_length": True,       # caller must supply length parameter
        "dims": {"M8": {"d": 8, "dk": 13, "k": 8, "s": 6, ...}},
    },
    "shaft_h6": { "sizes": ["Ø6","Ø8","Ø10",...], "has_length": True, ... },
    "iso15_6000": { ... },   # deep groove ball bearing
    ...
}
```

## builder.py rules
- Every builder returns a **Python source string** with `build_model()` defined.
- The string must satisfy the executor contract: `import cadquery as cq`, `build_model()`
  returns `cq.Workplane`, no `cq.exporters` calls.
- `_display_name(part_type, size, length)` builds the human-readable shelf name.
- Size strings: fasteners → `"M8"`, bearings/shafts → `"Ø10"` (Unicode Ø, not letter O).
- `has_length: True` → `length` (mm, float) must be passed by the caller.

## Usage pattern
```python
from caid_lite.catalog.builder import build_catalog_code
from caid_lite.catalog.data import CATALOG

info   = CATALOG["iso4762"]
code   = build_catalog_code("iso4762", size="M8", length=30.0)
# code is a complete Python script; pass to SessionManager._run_catalog()
```

## Dependency constraints
- `data.py`: stdlib only.
- `builder.py`: imports `data.CATALOG`; no CadQuery import (the returned string has it).
- No imports from `llm`, `session`, `assembly`, or `api`.
