"""Invalid CadQuery fixtures — each one triggers a specific failure mode.

All constants are Python source strings that the Sandbox will reject.
These do NOT require CadQuery to be installed (most fail before the import).
"""

# ── Contract violations ───────────────────────────────────────────────────────

NO_BUILD_MODEL = """\
import cadquery as cq

# This code never defines build_model(), so the runner rejects it.
x = 42
"""

NON_CALLABLE_BUILD_MODEL = """\
# build_model exists but is not a function
build_model = "I am not callable"
"""

# ── Runtime errors ────────────────────────────────────────────────────────────

RAISES_IN_BUILD_MODEL = """\
def build_model():
    raise RuntimeError("Deliberate error inside build_model")
"""

RAISES_AT_MODULE_LEVEL = """\
raise ValueError("Error at module level, before build_model is even defined")

def build_model():
    pass
"""

# ── Type violations ───────────────────────────────────────────────────────────

WRONG_RETURN_TYPE_STRING = """\
def build_model():
    return "I am not a Workplane"
"""

WRONG_RETURN_TYPE_NONE = """\
def build_model():
    return None
"""

WRONG_RETURN_TYPE_INT = """\
def build_model():
    return 42
"""

# ── Syntax errors ─────────────────────────────────────────────────────────────

SYNTAX_ERROR = """\
def build_model(:
    return None
"""

# ── Forbidden I/O (valid Python but violates spirit of the contract) ──────────

CALLS_EXPORTERS = """\
import cadquery as cq


def build_model():
    result = cq.Workplane("XY").box(1, 1, 1)
    cq.exporters.export(result, "output.step")  # should NOT be here
    return result
"""
