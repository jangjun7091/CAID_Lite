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
