"""Assembly routes: /api/assembly/... — multi-part assembly CRUD and solve."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..deps import get_manager
from ...assembly.manager import AssemblyManager
from ...session.manager import SessionManager

router = APIRouter(tags=["assembly"])


# ── Dependency ────────────────────────────────────────────────────────────────

def get_asm_manager(request: Request) -> AssemblyManager:
    """Inject AssemblyManager singleton from app state."""
    return request.app.state.asm_manager


# ── Request models ─────────────────────────────────────────────────────────────

class CreateAssemblyRequest(BaseModel):
    name: str = Field(default="", description="Optional assembly name")


class AddPartFromShelfRequest(BaseModel):
    part_ref_id: str = Field(..., description="PartEntry.id from the single-part shelf")


class AddPartFromCatalogRequest(BaseModel):
    """Add a catalog-generated part that already exists on the shelf."""
    part_ref_id: str = Field(..., description="PartEntry.id generated from catalog")


class UpdatePartColorRequest(BaseModel):
    color: str = Field(..., description="Hex color, e.g. '#7ec8e3'")


class AddConstraintRequest(BaseModel):
    type: str         = Field(..., description="Constraint kind: Plane/Axis/Point/Fixed/FixedPlane/FixedAxis")
    part_a: str       = Field(..., description="AssemblyPart.id (within the assembly)")
    selector_a: str   = Field(default="", description="Face selector for part_a, e.g. '>Z'")
    part_b: Optional[str] = Field(default=None, description="AssemblyPart.id for second part (None = world fixed)")
    selector_b: str   = Field(default="", description="Face selector for part_b")
    param: float      = Field(default=0.0, description="Offset/angle parameter")


# ── Session CRUD ──────────────────────────────────────────────────────────────

@router.get("/assembly", response_model=List[Dict[str, Any]])
def list_assemblies(
    asm: AssemblyManager = Depends(get_asm_manager),
) -> List[Dict[str, Any]]:
    """Return all assembly sessions."""
    return [s.to_dict() for s in asm.list_sessions()]


@router.post("/assembly", response_model=Dict[str, Any])
def create_assembly(
    body: CreateAssemblyRequest,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Create a new empty assembly session."""
    session = asm.create_session(name=body.name)
    return session.to_dict()


@router.get("/assembly/{asm_id}", response_model=Dict[str, Any])
def get_assembly(
    asm_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Return a single assembly session."""
    session = asm.get_session(asm_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Assembly '{asm_id}' not found.")
    return session.to_dict()


@router.delete("/assembly/{asm_id}", status_code=204)
def delete_assembly(
    asm_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> None:
    """Delete an assembly session."""
    if not asm.delete_session(asm_id):
        raise HTTPException(status_code=404, detail=f"Assembly '{asm_id}' not found.")


# ── Part management ───────────────────────────────────────────────────────────

@router.post("/assembly/{asm_id}/parts/from-shelf", response_model=Dict[str, Any])
def add_part_from_shelf(
    asm_id: str,
    body: AddPartFromShelfRequest,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Add a ready part from the single-part shelf to the assembly.

    The part must have ``status="ready"`` and a STEP export available.
    """
    try:
        part = asm.add_part_from_shelf(asm_id, body.part_ref_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return part.to_dict()


@router.post("/assembly/{asm_id}/parts/from-catalog", response_model=Dict[str, Any])
def add_part_from_catalog(
    asm_id: str,
    body: AddPartFromCatalogRequest,
    asm: AssemblyManager = Depends(get_asm_manager),
    manager: SessionManager = Depends(get_manager),
) -> Dict[str, Any]:
    """Add a catalog part (already generated on the shelf) to the assembly.

    Use ``POST /api/catalog/insert`` first to generate the part, then
    reference its PartEntry.id here.
    """
    part_entry = manager.get_part(body.part_ref_id)
    if part_entry is None:
        raise HTTPException(status_code=404, detail=f"Part '{body.part_ref_id}' not found.")
    if part_entry.status != "ready":
        raise HTTPException(
            status_code=400,
            detail=f"Part '{body.part_ref_id}' is not ready yet (status={part_entry.status}).",
        )
    if not part_entry.exports.get("step"):
        raise HTTPException(status_code=400, detail="Part has no STEP export.")
    try:
        part = asm.add_part_from_catalog(
            asm_id      = asm_id,
            step_path   = part_entry.exports["step"],
            stl_path    = part_entry.exports.get("stl", ""),
            name        = part_entry.name,
            part_ref_id = body.part_ref_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return part.to_dict()


@router.post("/assembly/{asm_id}/parts/upload", response_model=Dict[str, Any])
async def upload_part(
    asm_id: str,
    file: UploadFile = File(..., description="STEP file (.step or .stp)"),
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Upload an external STEP file and add it to the assembly."""
    session = asm.get_session(asm_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Assembly '{asm_id}' not found.")

    filename = file.filename or "uploaded.step"
    if not filename.lower().endswith((".step", ".stp")):
        raise HTTPException(status_code=400, detail="File must be a STEP file (.step or .stp).")

    # Save upload to a stable location
    import uuid
    upload_dir = Path("outputs") / "uploads" / asm_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    part_id  = str(uuid.uuid4())
    out_path = upload_dir / f"{part_id}.step"

    content = await file.read()
    out_path.write_bytes(content)

    name = Path(filename).stem
    try:
        part = asm.add_part_from_upload(asm_id, str(out_path), name=name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return part.to_dict()


@router.delete("/assembly/{asm_id}/parts/{part_id}", status_code=204)
def remove_part(
    asm_id: str,
    part_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> None:
    """Remove a part (and all its constraints) from the assembly."""
    if not asm.remove_part(asm_id, part_id):
        raise HTTPException(status_code=404, detail="Part not found in assembly.")


@router.patch("/assembly/{asm_id}/parts/{part_id}/color", response_model=Dict[str, Any])
def update_part_color(
    asm_id: str,
    part_id: str,
    body: UpdatePartColorRequest,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Update a part's display color."""
    if not asm.update_part_color(asm_id, part_id, body.color):
        raise HTTPException(status_code=404, detail="Part not found in assembly.")
    session = asm.get_session(asm_id)
    return session.to_dict()  # type: ignore[union-attr]


# ── Constraint management ─────────────────────────────────────────────────────

@router.post("/assembly/{asm_id}/constraints", response_model=Dict[str, Any])
def add_constraint(
    asm_id: str,
    body: AddConstraintRequest,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Add a positional/orientational constraint to the assembly."""
    valid_types = {"Plane", "Axis", "Point", "Fixed", "FixedPlane", "FixedAxis"}
    if body.type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown constraint type '{body.type}'. Valid: {sorted(valid_types)}",
        )
    try:
        con = asm.add_constraint(
            asm_id          = asm_id,
            constraint_type = body.type,
            part_a          = body.part_a,
            selector_a      = body.selector_a,
            part_b          = body.part_b,
            selector_b      = body.selector_b,
            param           = body.param,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return con.to_dict()


@router.delete("/assembly/{asm_id}/constraints/{con_id}", status_code=204)
def remove_constraint(
    asm_id: str,
    con_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> None:
    """Remove a constraint from the assembly."""
    if not asm.remove_constraint(asm_id, con_id):
        raise HTTPException(status_code=404, detail="Constraint not found in assembly.")


# ── NL constraint parsing (Phase 2) ──────────────────────────────────────────

class NLConstrainRequest(BaseModel):
    message: str = Field(..., description="Natural-language assembly instruction")


@router.post("/assembly/{asm_id}/nl-constrain", response_model=Dict[str, Any])
def nl_constrain(
    asm_id: str,
    body: NLConstrainRequest,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Parse a natural-language constraint instruction and add the constraints.

    Returns ``{"added": [<constraint dicts>], "session": <session dict>}``.
    Requires the server to be configured with an LLM backend.
    """
    try:
        added = asm.parse_nl_constraints(asm_id, body.message)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    session = asm.get_session(asm_id)
    return {
        "added":   [c.to_dict() for c in added],
        "session": session.to_dict(),  # type: ignore[union-attr]
    }


# ── Solve & export ────────────────────────────────────────────────────────────

@router.post("/assembly/{asm_id}/solve", response_model=Dict[str, Any])
async def solve_assembly(
    asm_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> Dict[str, Any]:
    """Trigger assembly constraint solving.

    Returns immediately with ``status="solving"``.
    Progress and result are streamed via ``GET /api/events`` SSE:
      - ``assembly.status_changed``
      - ``assembly.solved``
      - ``assembly.failed``
    """
    try:
        await asm.solve(asm_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    session = asm.get_session(asm_id)
    return session.to_dict()  # type: ignore[union-attr]


@router.get("/assembly/{asm_id}/step")
def download_assembly_step(
    asm_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> FileResponse:
    """Download the assembled STEP file."""
    session = asm.get_session(asm_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Assembly '{asm_id}' not found.")
    step_path = session.exports.get("step")
    if not step_path or not Path(step_path).is_file():
        raise HTTPException(
            status_code=404,
            detail="STEP file not available. Solve the assembly first.",
        )
    safe_name = session.name.replace(" ", "_")[:40] or "assembly"
    return FileResponse(
        step_path,
        media_type="application/octet-stream",
        filename=f"{safe_name}.step",
    )


@router.get("/assembly/{asm_id}/stl")
def download_assembly_stl(
    asm_id: str,
    asm: AssemblyManager = Depends(get_asm_manager),
) -> FileResponse:
    """Download the assembled STL file."""
    session = asm.get_session(asm_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Assembly '{asm_id}' not found.")
    stl_path = session.exports.get("stl")
    if not stl_path or not Path(stl_path).is_file():
        raise HTTPException(
            status_code=404,
            detail="STL file not available. Solve the assembly first.",
        )
    safe_name = session.name.replace(" ", "_")[:40] or "assembly"
    return FileResponse(
        stl_path,
        media_type="application/octet-stream",
        filename=f"{safe_name}.stl",
    )
