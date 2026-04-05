"""Valid CadQuery fixture satisfying the build_model() contract.

``SOURCE`` is a Python source string that the Sandbox can execute directly.
Used in integration tests that require a real CadQuery installation.
"""

SOURCE = """\
import cadquery as cq


def build_model():
    \"\"\"Simple parametric box — fastest geometry to validate the pipeline.\"\"\"
    width = 50.0
    height = 40.0
    thickness = 5.0

    return (
        cq.Workplane("XY")
        .box(width, height, thickness)
    )
"""

SOURCE_WITH_HOLES = """\
import cadquery as cq


def build_model():
    \"\"\"Mounting bracket with four M4 clearance holes.\"\"\"
    width = 60.0
    height = 40.0
    thickness = 6.0
    hole_dia = 4.5
    inset = 8.0

    return (
        cq.Workplane("XY")
        .box(width, height, thickness)
        .faces(">Z")
        .workplane()
        .rect(width - inset * 2, height - inset * 2, forConstruction=True)
        .vertices()
        .hole(hole_dia)
    )
"""

SOURCE_CYLINDER_WITH_HOLE = """\
import cadquery as cq


def build_model():
    \"\"\"Cylinder with a central through-hole.

    This exercises the cq.Compound acceptance fix: .hole() produces a
    Compound wrapping a Solid, not a bare cq.Solid.  The runner must
    set is_solid=True via len(shape.Solids()) > 0.
    \"\"\"
    outer_dia = 30.0
    inner_dia = 10.0
    height = 20.0

    return (
        cq.Workplane("XY")
        .cylinder(height, outer_dia / 2)
        .faces(">Z")
        .workplane()
        .hole(inner_dia)
    )
"""
