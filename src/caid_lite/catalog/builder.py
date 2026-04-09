"""CadQuery code generators for ISO standard parts.

Each builder returns a Python source string satisfying the ``build_model()``
contract: no arguments, returns ``cq.Workplane``.

CadQuery notes
--------------
- ``polygon(6, s)`` with default ``circumscribed=False`` → ``s`` is the
  **inscribed** circle diameter (flat-to-flat = across-flats).  Correct for
  ISO hex dimensions.
- ``circle(r).extrude(h)``  → cylinder from z=0 to z=h.
- ``slot2D(L, b)``           → stadium shape (rectangle + 2 semicircles),
  overall length L, width b.  Good for DIN 6885 Form A rounded-end keys.
"""

from __future__ import annotations

from .data import CATALOG


def _display_name(part_type: str, size: str, length: float | None) -> str:
    info = CATALOG[part_type]
    if length is not None:
        L = int(length) if float(length) == int(float(length)) else length
        return f"{info['name']} {size}×{L}"
    return f"{info['name']} {size}"


# ── Fasteners ────────────────────────────────────────────────────────────────

def _build_iso4762(dims: dict, size: str, length: float) -> str:
    d, dk, k, s = dims["d"], dims["dk"], dims["k"], dims["s"]
    socket_depth = round(k * 0.7, 3)
    return f"""\
import cadquery as cq


def build_model():
    # ISO 4762 {size} Socket Head Cap Screw  L={length} mm
    d  = {d}
    dk = {dk}
    k  = {k}
    s  = {s}    # hex socket (across flats)
    L  = {length}
    socket_depth = {socket_depth}

    shank = cq.Workplane("XY").circle(d / 2).extrude(L)
    head = (
        cq.Workplane("XY")
        .circle(dk / 2).extrude(k)
        .faces(">Z").workplane()
        .polygon(6, s)
        .cutBlind(-socket_depth)
        .translate((0, 0, L))
    )
    return shank.union(head)
"""


def _build_iso7380(dims: dict, size: str, length: float) -> str:
    d, dk, k, s = dims["d"], dims["dk"], dims["k"], dims["s"]
    socket_depth = round(k * 0.65, 3)
    return f"""\
import cadquery as cq


def build_model():
    # ISO 7380 {size} Button Head Socket Screw  L={length} mm
    d  = {d}
    dk = {dk}
    k  = {k}    # low-profile dome head
    s  = {s}    # hex socket (across flats)
    L  = {length}
    socket_depth = {socket_depth}

    shank = cq.Workplane("XY").circle(d / 2).extrude(L)
    head = (
        cq.Workplane("XY")
        .circle(dk / 2).extrude(k)
        .faces(">Z").workplane()
        .polygon(6, s)
        .cutBlind(-socket_depth)
        .translate((0, 0, L))
    )
    return shank.union(head)
"""


def _build_iso10642(dims: dict, size: str, length: float) -> str:
    d, dk, k, s = dims["d"], dims["dk"], dims["k"], dims["s"]
    shank_L = round(length - k, 3)
    socket_depth = round(k * 0.7, 3)
    return f"""\
import cadquery as cq


def build_model():
    # ISO 10642 {size} Countersunk Socket Screw  L={length} mm
    d       = {d}
    dk      = {dk}    # head outer diameter
    k       = {k}     # head height
    s       = {s}     # hex socket (across flats)
    shank_L = {shank_L}
    socket_depth = {socket_depth}

    shank = cq.Workplane("XY").circle(d / 2).extrude(shank_L)

    # Countersunk head: conical frustum (d/2 at base → dk/2 at top)
    head = (
        cq.Workplane("XY")
        .workplane(offset=shank_L)
        .circle(d / 2)
        .workplane(offset=k)
        .circle(dk / 2)
        .loft()
        .faces(">Z").workplane()
        .polygon(6, s)
        .cutBlind(-socket_depth)
    )
    return shank.union(head)
"""


def _build_iso4026(dims: dict, size: str, length: float) -> str:
    d, s = dims["d"], dims["s"]
    socket_depth = round(min(length * 0.5, s * 1.5), 3)
    return f"""\
import cadquery as cq


def build_model():
    # ISO 4026 {size} Set Screw (Grub)  L={length} mm
    d = {d}
    s = {s}    # hex socket (across flats)
    L = {length}
    socket_depth = {socket_depth}

    return (
        cq.Workplane("XY")
        .circle(d / 2)
        .extrude(L)
        .faces(">Z").workplane()
        .polygon(6, s)
        .cutBlind(-socket_depth)
    )
"""


def _build_iso4032(dims: dict, size: str) -> str:
    d, s, m = dims["d"], dims["s"], dims["m"]
    return f"""\
import cadquery as cq


def build_model():
    # ISO 4032 {size} Hex Nut
    d = {d}    # thread diameter
    s = {s}    # across flats (inscribed circle)
    m = {m}    # height

    return (
        cq.Workplane("XY")
        .polygon(6, s)
        .extrude(m)
        .faces(">Z").workplane()
        .hole(d)
    )
"""


def _build_iso7089(dims: dict, size: str) -> str:
    d1, d2, t = dims["d1"], dims["d2"], dims["t"]
    return f"""\
import cadquery as cq


def build_model():
    # ISO 7089 {size} Plain Washer
    d1 = {d1}    # inner diameter
    d2 = {d2}    # outer diameter
    t  = {t}     # thickness

    return (
        cq.Workplane("XY")
        .circle(d2 / 2)
        .extrude(t)
        .faces(">Z").workplane()
        .hole(d1)
    )
"""


# ── Bearings ─────────────────────────────────────────────────────────────────

def _build_bearing(dims: dict, label: str) -> str:
    d, D, B = dims["d"], dims["D"], dims["B"]
    return f"""\
import cadquery as cq


def build_model():
    # Deep Groove Ball Bearing {label}  d={d} D={D} B={B} mm
    d = {d}    # bore diameter
    D = {D}    # outer diameter
    B = {B}    # width

    # Simplified model: solid annular ring (outer + inner rings merged)
    # Outer ring
    outer = (
        cq.Workplane("XY")
        .circle(D / 2).extrude(B)
        .faces(">Z").workplane()
        .hole(D - (D - d) * 0.4)
    )
    # Inner ring
    inner = (
        cq.Workplane("XY")
        .circle(d / 2 + (D - d) * 0.2).extrude(B)
        .faces(">Z").workplane()
        .hole(d)
    )
    return outer.union(inner)
"""


# ── Shafts, Collars, Keys ────────────────────────────────────────────────────

def _build_shaft(dims: dict, size: str, length: float) -> str:
    d = dims["d"]
    return f"""\
import cadquery as cq


def build_model():
    # Shaft {size}  L={length} mm  (h6 tolerance)
    d = {d}     # diameter
    L = {length}  # length

    return cq.Workplane("XY").circle(d / 2).extrude(L)
"""


def _build_din705(dims: dict, size: str) -> str:
    d, D, B = dims["d"], dims["D"], dims["B"]
    return f"""\
import cadquery as cq


def build_model():
    # Set Collar DIN 705  bore={d} mm
    d = {d}    # bore diameter
    D = {D}    # outer diameter
    B = {B}    # width

    return (
        cq.Workplane("XY")
        .circle(D / 2).extrude(B)
        .faces(">Z").workplane()
        .hole(d)
    )
"""


def _build_din6885(dims: dict, size: str, length: float) -> str:
    b, h = dims["b"], dims["h"]
    return f"""\
import cadquery as cq


def build_model():
    # Parallel Key DIN 6885 Form A  {size}  L={length} mm
    b = {b}      # width
    h = {h}      # height
    L = {length}  # length (including rounded ends)

    # Form A: rounded ends (stadium shape)
    return (
        cq.Workplane("XY")
        .slot2D(L, b)
        .extrude(h)
    )
"""


# ── Profiles ─────────────────────────────────────────────────────────────────

def _build_tslot(dims: dict, size: str, length: float) -> str:
    w = dims["w"]
    slot_w = dims["slot_w"]
    slot_d = dims["slot_d"]
    center_d = dims["center_d"]
    return f"""\
import cadquery as cq


def build_model():
    # T-Slot Aluminum Profile {size}  L={length} mm
    w        = {w}         # section width = height
    L        = {length}    # extrusion length
    slot_w   = {slot_w}    # T-slot opening width
    slot_d   = {slot_d}    # T-slot depth (simplified rectangular channel)
    center_d = {center_d}  # center bore diameter

    result = cq.Workplane("XY").box(w, w, L)

    # Center bore along length
    result = result.faces(">Z").workplane().hole(center_d)

    # Rectangular slot approximation on all 4 faces
    for face in [">X", "<X", ">Y", "<Y"]:
        result = result.faces(face).workplane().rect(slot_w, L + 2).cutBlind(-slot_d)

    return result
"""


# ── Registry ─────────────────────────────────────────────────────────────────

_BUILDERS: dict = {
    "iso4762":    lambda d, s, L: _build_iso4762(d, s, L),
    "iso7380":    lambda d, s, L: _build_iso7380(d, s, L),
    "iso10642":   lambda d, s, L: _build_iso10642(d, s, L),
    "iso4026":    lambda d, s, L: _build_iso4026(d, s, L),
    "iso4032":    lambda d, s, _: _build_iso4032(d, s),
    "iso7089":    lambda d, s, _: _build_iso7089(d, s),
    "iso15_6000": lambda d, s, _: _build_bearing(d, s),
    "iso15_6200": lambda d, s, _: _build_bearing(d, s),
    "shaft_h6":   lambda d, s, L: _build_shaft(d, s, L),
    "din705":     lambda d, s, _: _build_din705(d, s),
    "din6885":    lambda d, s, L: _build_din6885(d, s, L),
    "tslot":      lambda d, s, L: _build_tslot(d, s, L),
}


# ── Public API ───────────────────────────────────────────────────────────────

def generate_code(
    part_type: str,
    size: str,
    length: float | None = None,
) -> tuple[str, str]:
    """Generate CadQuery source code for a catalog part.

    Args:
        part_type: Catalog key, e.g. ``"iso4762"``.
        size:      Size label, e.g. ``"M6"``.
        length:    Length in mm.  Required when ``has_length`` is True.

    Returns:
        ``(code, display_name)``

    Raises:
        ValueError: Unknown part_type / size, or missing length.
    """
    if part_type not in CATALOG:
        raise ValueError(f"Unknown part type: '{part_type}'")

    info = CATALOG[part_type]
    sizes = info["sizes"]

    if size not in sizes:
        raise ValueError(
            f"Unknown size '{size}' for '{part_type}'. "
            f"Valid: {', '.join(sizes)}"
        )

    if info["has_length"] and (length is None or length <= 0):
        raise ValueError(
            f"'{part_type}' requires a positive length in mm."
        )

    dims = sizes[size]
    code = _BUILDERS[part_type](dims, size, length)
    name = _display_name(part_type, size, length)
    return code, name
